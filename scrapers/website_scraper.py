import httpx
from bs4 import BeautifulSoup
from tenacity import retry, wait_exponential, stop_after_attempt
from scrapers.base import BaseScraper
from database.models import PageSnapshot
from detection.hasher import compute_hash

# Many websites block requests that don't look like a real browser.
# They check the User-Agent header — a string that identifies what software is making the request.
# Python's default httpx User-Agent is "python-httpx/0.x.x" — many sites block this.
# We impersonate a real Chrome browser on Windows to get past basic bot detection.
# Alternative: rotate User-Agents randomly per request; use residential proxies for
# stricter sites; or use a headless browser (Playwright) like jobs_scraper.py does.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


class WebsiteScraper(BaseScraper):

    @retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(3))
    async def scrape(self) -> list[PageSnapshot]:
        if not self.competitor.website_url:
            return []

        url = self.competitor.website_url
        # follow_redirects=True handles HTTP 301/302 redirects automatically.
        # Many company homepages redirect http:// to https:// — without this flag,
        # httpx would raise an error instead of following the redirect.
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=HEADERS) as client:
            response = await client.get(url)
            response.raise_for_status()

        # BeautifulSoup parses raw HTML into a searchable tree of tag objects.
        # "lxml" is the parser backend — it's faster than Python's built-in "html.parser"
        # and more lenient with malformed HTML than "html5lib".
        # Alternative: lxml directly (without BeautifulSoup) — faster but more verbose API.
        soup = BeautifulSoup(response.text, "lxml")

        # decompose() removes these tags AND all their children from the tree permanently.
        # <script> contains JavaScript code. <style> contains CSS. <noscript> is fallback HTML.
        # <svg> and <img> contain binary/vector data. None of this belongs in text we compare.
        # Without removal, get_text() would include all the JavaScript source code in the
        # snapshot — every library update would trigger a false "change detected."
        for tag in soup(["script", "style", "noscript", "svg", "img"]):
            tag.decompose()

        # get_text() extracts all visible text, using "\n" as separator between tags.
        # This flattens the HTML tree into a single readable string.
        text = soup.get_text(separator="\n")
        content_text = self._clean_text(text)

        return [PageSnapshot(
            competitor_id=self.competitor.id,
            source_type="website",
            url=url,
            content_hash=compute_hash(content_text),
            content_text=content_text,
        )]
