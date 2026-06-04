import httpx
from bs4 import BeautifulSoup
from tenacity import retry, wait_exponential, stop_after_attempt
from scrapers.base import BaseScraper
from database.models import PageSnapshot
from detection.hasher import compute_hash


class NewsScraper(BaseScraper):

    # @retry is a decorator from the tenacity library. It wraps the function so that if it
    # raises ANY exception, it waits and tries again automatically.
    # wait_exponential: 1st retry waits 2s, 2nd waits 4s, 3rd waits 8s (doubles each time, max 30s).
    # stop_after_attempt(3): give up after 3 total tries (1 original + 2 retries).
    # Alternative: manually write try/except with time.sleep() in a loop — more boilerplate.
    @retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(3))
    async def scrape(self) -> list[PageSnapshot]:
        if not self.competitor.news_query:
            return []

        # Google News RSS is free, requires no API key or login, and returns structured XML.
        # Alternative: Newsdata.io, GNews, or NewsAPI — they offer richer filtering but
        # require registration and have strict free-tier limits.
        # hl=en-IN: language hint (Hindi/English, India). gl=IN: geolocation India.
        # ceid=IN:en: combined country+language identifier for the feed.
        query = self.competitor.news_query.replace(" ", "+")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"

        # httpx.AsyncClient is the async equivalent of the popular `requests` library.
        # Why httpx over requests? requests is synchronous (blocking) — it freezes the
        # thread while waiting for the response. httpx.AsyncClient is non-blocking —
        # the event loop can run other tasks while waiting. This matters when scraping
        # multiple companies concurrently.
        # `async with` = async context manager: ensures the client connection is closed
        # even if an exception occurs inside the block.
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url)
            # raise_for_status() converts HTTP error codes (4xx, 5xx) into Python exceptions.
            # Without it, a 404 or 429 response would be silently treated as "success."
            response.raise_for_status()

        # "lxml-xml" is BeautifulSoup's XML parsing mode — required for RSS feeds.
        # The regular "lxml" mode is for HTML. Using the wrong mode produces wrong results.
        # Alternative: Python's built-in xml.etree.ElementTree — lower-level, more verbose.
        soup = BeautifulSoup(response.content, "lxml-xml")
        items = soup.find_all("item")[:10]  # <item> is the RSS tag for each news article

        lines = []
        for item in items:
            title = item.find("title").get_text(strip=True) if item.find("title") else ""
            pub_date = item.find("pubDate").get_text(strip=True) if item.find("pubDate") else ""
            source_tag = item.find("source")
            source = source_tag.get_text(strip=True) if source_tag else ""
            # Format each article as a single line — one line per article makes diffs readable.
            # When a new article appears, the diff shows a clean "+" line.
            lines.append(f"{pub_date} | {source} | {title}")

        content_text = self._clean_text("\n".join(lines))

        return [PageSnapshot(
            competitor_id=self.competitor.id,
            source_type="news",
            url=url,
            content_hash=compute_hash(content_text),
            content_text=content_text,
        )]
