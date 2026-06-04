from abc import ABC, abstractmethod
from database.models import CompetitorConfig, PageSnapshot
import re


# ABC = Abstract Base Class. It defines an interface that all scrapers must follow.
# Any class inheriting from ABC that doesn't implement all @abstractmethod methods
# will raise a TypeError when you try to instantiate it — caught at development time.
# Alternative: Python's "duck typing" — just trust that every scraper has a scrape() method
# with no enforcement. That works but breaks silently if you forget to implement it.
# Another alternative: typing.Protocol (structural subtyping) — checks shape without inheritance.
class BaseScraper(ABC):
    def __init__(self, competitor: CompetitorConfig):
        self.competitor = competitor

    # @abstractmethod marks this as "must be overridden by subclasses."
    # The ... body (Ellipsis) is a conventional placeholder — same as `pass` but signals intent.
    # async def means this is a coroutine — callers must `await` it.
    # We chose async so scrapers can be run concurrently with asyncio.gather() in future.
    # Alternative: regular (synchronous) def — simpler, but you'd need threads for concurrency.
    @abstractmethod
    async def scrape(self) -> list[PageSnapshot]:
        """Fetch data and return a list of PageSnapshot objects."""
        ...

    # Shared utility available to all scrapers. Collapsed whitespace makes text diffs
    # cleaner — changes in spacing don't show up as false positives.
    def _clean_text(self, raw: str) -> str:
        # re.sub replaces matches of the pattern. [ \t]+ = one or more spaces or tabs.
        text = re.sub(r"[ \t]+", " ", raw)
        # \n{3,} = 3 or more consecutive newlines — collapse to 2 (one blank line).
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
