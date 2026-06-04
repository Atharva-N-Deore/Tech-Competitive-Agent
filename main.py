import time
# Python has a built-in module also called "signal" (for OS process signals like Ctrl+C).
# We rename it to os_signal to avoid clashing with our own signal_extractor module.
import signal as os_signal
from loguru import logger
from config.settings import LOG_PATH, LOG_LEVEL
from database.db import initialize_db
from database import db
from config.competitors import COMPETITORS
from scheduler.jobs import create_scheduler, scrape_news, scrape_github

# loguru is a drop-in replacement for Python's built-in `logging` module.
# Advantages over built-in logging:
#   - One-line setup: logger.add() replaces 10+ lines of Handler/Formatter boilerplate
#   - Automatic colorization in terminal
#   - rotation="1 day": creates a new log file every day (e.g., agent.2024-06-04.log)
#   - retention="7 days": automatically deletes log files older than 7 days
# The format string defines how each log line looks in the file.
logger.add(LOG_PATH, rotation="1 day", retention="7 days", level=LOG_LEVEL,
           format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")


# Populates the `competitors` DB table from the Python config list.
# This runs on every startup but only inserts rows that don't already exist
# (INSERT OR IGNORE in db.insert_competitor). It also populates comp.id so
# scrapers and the scheduler know each competitor's integer database ID.
def seed_competitors():
    existing = {c["slug"] for c in db.get_all_active_competitors()}
    for comp in COMPETITORS:
        if comp.slug not in existing:
            comp.id = db.insert_competitor(comp)
            logger.info(f"Seeded competitor: {comp.name}")
        else:
            # Competitor already in DB — just load its ID into the in-memory object.
            comp.id = db.get_competitor_by_slug(comp.slug)["id"]
            logger.debug(f"Loaded competitor: {comp.name} (id={comp.id})")


def main():
    logger.info("=" * 60)
    logger.info("Starting Competitive Intelligence Agent")
    logger.info("=" * 60)

    # Step 1: Run schema.sql to create tables (safe to call every startup — IF NOT EXISTS).
    initialize_db()

    # Step 2: Sync the competitors table with the config file.
    seed_competitors()

    # Step 3: Run an immediate first scrape so you have data right away.
    # Without this you'd wait up to 6 hours for the first scheduled run.
    # We only run news + github (fast) and skip jobs + websites (slow Playwright scrapes).
    logger.info("Running initial scrape (news + github)...")
    scrape_news()
    scrape_github()

    # Step 4: Set up and start the background scheduler.
    scheduler = create_scheduler()
    scheduler.start()
    logger.success("Scheduler started. Monitoring: " +
                   ", ".join(c.name for c in COMPETITORS if c.is_active))
    logger.info("Press Ctrl+C to stop.")

    # Step 5: Register a Ctrl+C handler for clean shutdown.
    # os_signal.SIGINT is the signal sent when you press Ctrl+C.
    # Without this handler, Ctrl+C would kill the process abruptly — the scheduler
    # might be mid-job and leave the DB in an inconsistent state.
    def shutdown(signum, frame):
        logger.info("Shutting down scheduler...")
        # wait=False: don't wait for running jobs to finish — exit immediately.
        # Change to wait=True if you want the current scrape to complete before shutdown.
        scheduler.shutdown(wait=False)
        raise SystemExit(0)

    os_signal.signal(os_signal.SIGINT, shutdown)

    # Step 6: Keep the main thread alive.
    # APScheduler's BackgroundScheduler runs on a daemon thread — it only lives as long
    # as the main thread is alive. Without this loop, main() would return immediately
    # and the entire program would exit, killing the scheduler thread.
    # time.sleep(60): sleep for 60 seconds then loop — the main thread does nothing but
    # wait, while the scheduler runs its jobs on the background thread.
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
