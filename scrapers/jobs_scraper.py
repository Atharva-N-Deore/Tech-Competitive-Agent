from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from tenacity import retry, wait_exponential, stop_after_attempt
from loguru import logger
from scrapers.base import BaseScraper
from database.models import PageSnapshot
from detection.hasher import compute_hash

# Career pages are almost always JavaScript-rendered (React, Vue, Angular).
# A plain HTTP request returns an empty <div id="root"></div> with no job listings.
# Only a real browser that executes the JavaScript gets the actual content.
#
# Playwright vs Selenium vs Puppeteer:
#   - Selenium: older, supports many browsers, but slower and more brittle.
#   - Puppeteer: Google's official Node.js browser automation — great, but requires Node.js.
#   - Playwright: Microsoft's library, supports Chromium/Firefox/WebKit, has both Python and
#     Node.js APIs, faster than Selenium, better async support. Best choice for Python projects.
#
# We try a list of CSS selectors that commonly wrap job listings. Different companies
# use different class names — this list covers common patterns.
# Alternative: use page.get_by_role("listitem") (Playwright's semantic selector) — more
# robust but may match too many elements on complex pages.
JOB_SELECTORS = [
    "[data-automation='job-title']",
    "[class*='job-title']",
    "[class*='position-title']",
    "[class*='role-title']",
    "h2[class*='title']",
    "h3[class*='title']",
    "li[class*='job']",
    "div[class*='job-card']",
    "article[class*='job']",
]


class JobsScraper(BaseScraper):

    # Longer retry delays than other scrapers (min=5s) because browser launches are heavy —
    # if one fails it's usually a resource issue that needs more recovery time.
    @retry(wait=wait_exponential(min=5, max=60), stop=stop_after_attempt(3))
    async def scrape(self) -> list[PageSnapshot]:
        if not self.competitor.careers_url:
            return []

        url = self.competitor.careers_url
        job_lines = []

        # async_playwright() is an async context manager that manages the Playwright process.
        # It must be used with `async with` so the browser subprocess is always cleaned up.
        # `p` gives you access to browser types: p.chromium, p.firefox, p.webkit.
        async with async_playwright() as p:
            # headless=True = run Chromium with no visible window (background mode).
            # Set headless=False to see the browser open — useful for debugging which
            # selector your page needs.
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                # wait_until="networkidle": Playwright waits until there are ≤0 active network
                # connections for 500ms — meaning all JavaScript API calls have completed.
                # Alternatives:
                #   "load": waits for the window.load event (DOM ready but JS may still run)
                #   "domcontentloaded": fastest, but content often isn't rendered yet
                #   "networkidle": slowest but most reliable for SPA (single-page apps)
                # timeout=60_000: milliseconds (60 seconds) — browser operations are slow.
                await page.goto(url, wait_until="networkidle", timeout=60_000)

                # Try each CSS selector in order — stop at the first one that matches.
                # query_selector_all() returns a list of all matching elements.
                for selector in JOB_SELECTORS:
                    elements = await page.query_selector_all(selector)
                    if elements:
                        for el in elements:
                            # inner_text() returns the rendered visible text of the element,
                            # stripping HTML tags. Equivalent to what a user reads on screen.
                            text = await el.inner_text()
                            if text.strip():
                                job_lines.append(text.strip())
                        break  # found matching elements — stop trying other selectors

                # Fallback: if no known selector matched, dump the entire page body text.
                # This is noisier but ensures we capture something for new/unknown career pages.
                if not job_lines:
                    body_text = await page.inner_text("body")
                    job_lines = [
                        line.strip()
                        for line in body_text.splitlines()
                        if line.strip()
                    ]

            except PlaywrightTimeout:
                # Some career pages are very slow or require a login — log and continue.
                # We imported TimeoutError as PlaywrightTimeout to avoid shadowing Python's
                # built-in TimeoutError.
                logger.warning(f"Timeout scraping jobs for {self.competitor.slug}")
            finally:
                # `finally` runs whether the try block succeeded or raised an exception.
                # Always close the browser — a leaked browser process wastes ~200MB of RAM.
                await browser.close()

        content_text = self._clean_text("\n".join(job_lines))
        return [PageSnapshot(
            competitor_id=self.competitor.id,
            source_type="jobs",
            url=url,
            content_hash=compute_hash(content_text),
            content_text=content_text,
        )]
