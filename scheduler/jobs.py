import asyncio
import time
from loguru import logger
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config.competitors import COMPETITORS
from database import db
from scrapers.jobs_scraper import JobsScraper
from scrapers.website_scraper import WebsiteScraper
from scrapers.github_scraper import GithubScraper
from scrapers.news_scraper import NewsScraper
from detection.hasher import content_changed
from detection.differ import generate_diff, compute_similarity
from detection.signal_extractor import extract_signals
from config.settings import SIMILARITY_THRESHOLD

# All scheduled times use IST (Indian Standard Time, UTC+5:30).
# pytz handles the UTC conversion automatically — APScheduler stores jobs in UTC internally.
# Alternative: use UTC everywhere and mentally convert. Using IST is more intuitive
# for reading the schedule ("runs at 8am" = 8am IST, not 8am UTC which is 1:30pm IST).
IST = pytz.timezone("Asia/Kolkata")


# Called after every scrape. Implements the full change-detection pipeline:
# hash check → store snapshot → diff → similarity filter → signal extraction.
def _process_snapshot(snapshot, comp):
    # Look up the most recent snapshot for this exact (company, source_type, url) triple.
    previous = db.get_latest_snapshot(comp.id, snapshot.source_type, snapshot.url)

    # Fast path: hash check. SHA256 comparison is O(1) — instant.
    # If the content didn't change, stop immediately without touching the DB or running a diff.
    if previous and not content_changed(snapshot.content_text, previous["content_hash"]):
        logger.debug(f"No change: {comp.slug}/{snapshot.source_type}")
        return

    # Content changed (or this is the first snapshot) — store it.
    new_id = db.insert_snapshot(snapshot)

    if not previous:
        # First time we've scraped this URL — nothing to diff against yet.
        logger.info(f"First snapshot: {comp.slug}/{snapshot.source_type}")
        return

    # Slow path: compute text similarity ratio (0.0 to 1.0).
    # Pages often have minor cosmetic changes (today's date, ad rotation, session tokens).
    # If 98%+ of the content is the same, it's not strategically meaningful.
    similarity = compute_similarity(snapshot.content_text, previous["content_text"])
    if similarity > SIMILARITY_THRESHOLD:
        logger.debug(f"Minor change ({similarity:.1%}): {comp.slug}/{snapshot.source_type}")
        return

    # Significant change — generate the unified diff and store it.
    diff_text = generate_diff(previous["content_text"], snapshot.content_text)

    from database.models import DetectedChange
    change = DetectedChange(
        competitor_id=comp.id,
        source_type=snapshot.source_type,
        url=snapshot.url,
        previous_snapshot_id=previous["id"],
        current_snapshot_id=new_id,
        diff_text=diff_text,
        change_summary=f"Change in {snapshot.source_type} ({similarity:.0%} similar)",
    )
    change_id = db.insert_change(change)
    change.id = change_id  # update the object with the DB-assigned ID so signal_extractor can use it

    # Rule-based signal extraction — fast, free, runs before Claude.
    signals = extract_signals(change, comp.id)
    for signal in signals:
        db.insert_signal(signal)
        logger.info(f"Signal [{signal.signal_type}] for {comp.slug}")


# Generic job runner: takes a scraper class and runs it for every active competitor.
# Why take the class as an argument instead of writing separate functions?
# All four scrapers (news, github, website, jobs) follow the same pipeline —
# instantiate, scrape, process snapshots. Parameterizing avoids 4 identical functions.
def _run_scraper_job(scraper_class, source_type: str):
    for comp in COMPETITORS:
        if not comp.is_active or comp.id is None:
            continue
        start = time.time()
        try:
            # APScheduler runs jobs in THREADS, not in an async event loop.
            # Our scrapers are async (they use `await`). To run async code from a thread,
            # you must create a new event loop for that thread, run the coroutine
            # synchronously to completion, then close the loop.
            # Alternative: use asyncio.run() — cleaner one-liner, but creates AND destroys
            # the loop for you (same thing under the hood).
            loop = asyncio.new_event_loop()
            scraper = scraper_class(comp)
            snapshots = loop.run_until_complete(scraper.scrape())
            loop.close()

            for snapshot in snapshots:
                _process_snapshot(snapshot, comp)

            db.log_run(source_type, comp.slug, "success", time.time() - start)

        except Exception as e:
            # Catch-all: log the error and continue with the next competitor.
            # We don't want one failed scrape to crash the entire job.
            logger.exception(f"Scrape failed: {source_type}/{comp.slug}: {e}")
            db.log_run(source_type, comp.slug, "failed", time.time() - start, str(e))


# Individual job functions — named clearly for the APScheduler job registry.
# These are what APScheduler calls on each trigger. They delegate immediately to
# _run_scraper_job to avoid code duplication.
def scrape_news():
    logger.info("Job: scrape_news")
    _run_scraper_job(NewsScraper, "news")


def scrape_github():
    logger.info("Job: scrape_github")
    _run_scraper_job(GithubScraper, "github")


def scrape_jobs():
    logger.info("Job: scrape_jobs")
    _run_scraper_job(JobsScraper, "jobs")


def scrape_websites():
    logger.info("Job: scrape_websites")
    _run_scraper_job(WebsiteScraper, "website")


def run_analysis():
    logger.info("Job: run_analysis")
    from agent.analyst import analyze_competitor
    for comp in COMPETITORS:
        if not comp.is_active or comp.id is None:
            continue
        # Only analyze competitors that have new, unprocessed signals — skip the rest.
        signals = db.get_unprocessed_signals(comp.id, days_back=7)
        if not signals:
            continue
        signal_ids = [s["id"] for s in signals]
        logger.info(f"Analyzing {comp.slug} ({len(signal_ids)} signals)")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(analyze_competitor(comp.slug, signal_ids))
        loop.close()


def daily_report():
    logger.info("Job: daily_report")
    from reports.reporter import generate_daily_report
    generate_daily_report()


# Creates and configures the APScheduler instance.
# BackgroundScheduler runs on a daemon thread — it keeps running while the main thread
# is alive (the while True loop in main.py) and stops when the process exits.
# Alternative: BlockingScheduler — occupies the main thread and has no while True loop.
# We use BackgroundScheduler so main.py can still handle Ctrl+C signals cleanly.
def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=IST)

    # CronTrigger(minute=0) = fire at minute 0 of every hour = once per hour.
    # CronTrigger(hour="*/2") = fire at hour 0, 2, 4, 6, 8... = every 2 hours.
    # CronTrigger(hour="6,12,18,0") = fire at 6am, 12pm, 6pm, midnight IST.
    # This is the same syntax as Unix cron: */2 means "every 2 units."
    scheduler.add_job(scrape_news,     CronTrigger(minute=0),          id="scrape_news")
    scheduler.add_job(scrape_github,   CronTrigger(hour="*/2"),        id="scrape_github")
    scheduler.add_job(scrape_jobs,     CronTrigger(hour="*/4"),        id="scrape_jobs")
    scheduler.add_job(scrape_websites, CronTrigger(hour="*/6"),        id="scrape_websites")
    scheduler.add_job(run_analysis,    CronTrigger(hour="6,12,18,0"),  id="run_analysis")
    scheduler.add_job(daily_report,    CronTrigger(hour=8, minute=0),  id="daily_report")
    return scheduler
