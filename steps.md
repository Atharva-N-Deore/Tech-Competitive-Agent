# Competitive Intelligence Agent — Implementation Steps

This document walks through every step to build the project from scratch. It is written to teach, not just instruct — each step explains the *why* behind the technical choices.

---

## Table of Contents

1. [Phase 0 — Project Bootstrap](#phase-0--project-bootstrap)
2. [Phase 1 — Data Models and Database](#phase-1--data-models-and-database)
3. [Phase 2 — Web Scraping Layer](#phase-2--web-scraping-layer)
4. [Phase 3 — Change Detection Engine](#phase-3--change-detection-engine)
5. [Phase 4 — The Claude AI Agent](#phase-4--the-claude-ai-agent)
6. [Phase 5 — Scheduler](#phase-5--scheduler)
7. [Phase 6 — Reports and Entry Point](#phase-6--reports-and-entry-point)
8. [Verification and Testing](#verification-and-testing)

---

## Phase 0 — Project Bootstrap

### What is a virtual environment and why do we need one?

A **virtual environment** is an isolated Python installation for a single project. Without it, every project on your machine shares the same global Python packages. This causes "dependency hell" — Project A needs `httpx==0.27`, Project B needs `httpx==0.25`, and they break each other.

A virtual environment solves this by creating a self-contained folder (`.venv/`) with its own `python.exe` and its own `site-packages/` directory. When you activate it, `python` and `pip` point to *that* folder, not the global one.

### Step 1 — Create the virtual environment

```powershell
cd "c:\Users\CCTech_Atharva\Codes\Competitive Intelligence Agent"
python -m venv .venv
```

- `python -m venv` invokes Python's built-in `venv` module.
- `.venv` is the folder name — it is conventional to call it `.venv` or `venv`.

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

Your terminal prompt will now show `(.venv)` prefix — this tells you the virtual environment is active. Every `pip install` from now on installs into `.venv/`, not globally.

### Step 2 — Create `requirements.txt`

This file lists every third-party package the project needs. `pip install -r requirements.txt` reads it and installs everything at once.

Create `requirements.txt` at the project root with:

```
anthropic>=0.40.0
apscheduler>=3.10.4
playwright>=1.44.0
httpx>=0.27.0
beautifulsoup4>=4.12.3
lxml>=5.2.0
pydantic>=2.7.0
python-dotenv>=1.0.0
rich>=13.7.4
loguru>=0.7.2
tenacity>=8.3.0
pytz>=2024.1
```

The `>=` syntax means "this version or any newer compatible version." This gives flexibility while setting a minimum.

### Step 3 — Install packages

```powershell
pip install -r requirements.txt
```

Then install Playwright's browser binary (a separate step because Playwright downloads a full Chromium browser, not just a Python package):

```powershell
playwright install chromium
```

Without this second command, Playwright knows *how* to control a browser but has no browser to control. It downloads ~150MB of Chromium into Playwright's own cache folder.

### Step 4 — Create the `.env` file

Environment variables are the standard way to store secrets (API keys, tokens) without hardcoding them in source files. A `.env` file is a simple key=value text file that the `python-dotenv` library reads and injects into `os.environ` at runtime.

Create `.env` at the project root:

```
ANTHROPIC_API_KEY=sk-ant-your-key-here
GITHUB_TOKEN=ghp_your_token_here
LOG_LEVEL=INFO
```

**Critical:** Add `.env` to `.gitignore` immediately. A leaked API key can result in unauthorized charges or security breaches.

Also create `.env.example` (this *is* committed to git — it shows teammates what variables are needed without exposing values):

```
ANTHROPIC_API_KEY=
GITHUB_TOKEN=
LOG_LEVEL=INFO
```

### Step 5 — Create `.gitignore`

```
.env
.venv/
__pycache__/
*.pyc
data/
logs/
*.db
```

### Step 6 — Create the directory structure

Create these folders (empty `__init__.py` files make directories into Python packages — Python will not import from a folder without one):

```
config/
database/
scrapers/
detection/
agent/
scheduler/
reports/
data/
logs/
```

In each of `config/`, `database/`, `scrapers/`, `detection/`, `agent/`, `scheduler/`, `reports/` — create an empty `__init__.py` file.

---

## Phase 1 — Data Models and Database

### What is SQLite and why use it here?

**SQLite** is a serverless, file-based relational database. Unlike PostgreSQL or MySQL, it does not run as a separate process — the entire database lives in a single file (`intelligence.db`). For a locally-running agent with no concurrent users, SQLite is perfect.

**`sqlite3`** is part of Python's standard library — no installation needed.

### Step 7 — Design the database schema (`database/schema.sql`)

A **schema** is the blueprint of a database — it defines what tables exist, what columns each has, and what data type each column stores.

We have six tables. Here they are with full explanations:

```sql
-- Table 1: competitors
-- The master list of companies we are monitoring.
-- "slug" is a URL-friendly identifier like "razorpay" used as a key in code.
CREATE TABLE IF NOT EXISTS competitors (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    slug         TEXT UNIQUE NOT NULL,
    website_url  TEXT,
    careers_url  TEXT,
    github_org   TEXT,
    news_query   TEXT,
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Table 2: page_snapshots
-- Every time we scrape a URL, we store the extracted text and a SHA256 hash here.
-- This is the "memory" of the agent — it knows what every competitor's page
-- looked like at every point in time.
-- source_type is one of: "jobs", "website", "github", "news"
CREATE TABLE IF NOT EXISTS page_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id   INTEGER NOT NULL REFERENCES competitors(id),
    source_type     TEXT NOT NULL,
    url             TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    content_text    TEXT NOT NULL,
    scraped_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Index for fast "get latest snapshot for this company+source" queries
CREATE INDEX IF NOT EXISTS idx_snapshots_lookup
    ON page_snapshots (competitor_id, source_type, url);

-- Table 3: detected_changes
-- When a hash check reveals the content changed, we compute a diff and store it here.
-- "is_processed" = 0 means Claude has not analyzed this change yet.
-- Linking previous_snapshot_id and current_snapshot_id lets us reconstruct
-- the exact before/after at any point in the future.
CREATE TABLE IF NOT EXISTS detected_changes (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id         INTEGER NOT NULL REFERENCES competitors(id),
    source_type           TEXT NOT NULL,
    url                   TEXT,
    previous_snapshot_id  INTEGER REFERENCES page_snapshots(id),
    current_snapshot_id   INTEGER REFERENCES page_snapshots(id),
    diff_text             TEXT NOT NULL,
    change_summary        TEXT,
    detected_at           TEXT NOT NULL DEFAULT (datetime('now')),
    is_processed          INTEGER NOT NULL DEFAULT 0
);

-- Table 4: signals
-- Structured, typed events extracted from changes by rule-based code (no LLM).
-- signal_type is a string like "hiring_surge_ml", "pricing_change", "funding_news".
-- signal_data is a JSON string storing structured details about the signal.
-- confidence is a float from 0.0 (uncertain) to 1.0 (very confident).
CREATE TABLE IF NOT EXISTS signals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id      INTEGER REFERENCES detected_changes(id),
    competitor_id  INTEGER NOT NULL REFERENCES competitors(id),
    signal_type    TEXT NOT NULL,
    signal_data    TEXT NOT NULL,
    confidence     REAL NOT NULL DEFAULT 0.5,
    detected_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Table 5: analyses
-- Claude's strategic analysis of a batch of signals for one competitor.
-- signal_ids is a JSON array like [3, 5, 8] — the IDs of signals analyzed.
-- strategic_implications stores the extracted bullet points as JSON array.
CREATE TABLE IF NOT EXISTS analyses (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id           INTEGER NOT NULL REFERENCES competitors(id),
    signal_ids              TEXT NOT NULL,
    analysis_text           TEXT NOT NULL,
    strategic_implications  TEXT,
    model_used              TEXT,
    tokens_used             INTEGER,
    analyzed_at             TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Table 6: run_log
-- Records every scheduler job execution for debugging.
-- If a scrape fails silently, this is where you find out.
CREATE TABLE IF NOT EXISTS run_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name         TEXT NOT NULL,
    competitor_slug  TEXT,
    status           TEXT NOT NULL,
    error_message    TEXT,
    duration_seconds REAL,
    ran_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**Key design decisions:**
- All timestamps use `TEXT` in ISO 8601 format (`2024-06-04T14:30:00`) — SQLite has no native datetime type. ISO strings sort chronologically, which makes `ORDER BY scraped_at DESC` work correctly.
- `REFERENCES` is the foreign key syntax. It prevents orphan records (e.g., a snapshot referring to a competitor that was deleted).
- `CREATE TABLE IF NOT EXISTS` makes the schema idempotent — safe to run on every startup.

### Step 8 — Write `database/db.py`

This module is the single interface between the application code and SQLite. No other module imports `sqlite3` directly — everything goes through `db.py`. This is the **repository pattern**: all database operations are in one place, making them easy to test and refactor.

Key functions to implement:

**`get_connection() -> sqlite3.Connection`**

```python
import sqlite3
from pathlib import Path
from config.settings import DB_PATH

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # rows behave like dicts: row["name"] instead of row[0]
    conn.execute("PRAGMA foreign_keys = ON")  # enforce REFERENCES constraints
    return conn
```

`sqlite3.Row` is important for readability. Without it, you get tuples and have to remember column order. With it, rows are dict-like: `row["competitor_id"]`.

**`initialize_db()`**

```python
def initialize_db():
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text()
    with get_connection() as conn:
        conn.executescript(sql)
```

This reads and executes all the `CREATE TABLE IF NOT EXISTS` statements in `schema.sql`.

**`insert_snapshot(snapshot: PageSnapshot) -> int`** — inserts a row and returns the new `id`.

**`get_latest_snapshot(competitor_id, source_type, url) -> dict | None`** — fetches the most recent snapshot for a given company + source combination. Used by change detection to get the "previous" state.

**`insert_change(change: DetectedChange) -> int`**

**`insert_signal(signal: Signal) -> int`**

**`get_unprocessed_signals(competitor_id: int, days_back: int = 7) -> list[dict]`** — returns all signals where `is_processed = 0` for a given competitor in the last N days. Called by the analyst agent before each analysis run.

**`mark_signals_processed(signal_ids: list[int])`** — updates `is_processed = 1` after Claude has analyzed them.

**`insert_analysis(analysis: Analysis) -> int`**

**`get_competitor_by_slug(slug: str) -> dict | None`**

**`get_all_active_competitors() -> list[dict]`**

### Step 9 — Write `database/models.py`

**Pydantic** is a data validation library. You define a class that inherits from `BaseModel` and annotate its fields with Python types. Pydantic automatically validates that incoming data matches those types and raises a clear error if not.

```python
from pydantic import BaseModel
from typing import Literal
from datetime import datetime

class CompetitorConfig(BaseModel):
    id: int | None = None
    name: str
    slug: str
    website_url: str | None = None
    careers_url: str | None = None
    github_org: str | None = None
    news_query: str | None = None
    is_active: bool = True

class PageSnapshot(BaseModel):
    id: int | None = None
    competitor_id: int
    source_type: Literal["jobs", "website", "github", "news"]
    url: str
    content_hash: str
    content_text: str
    scraped_at: datetime | None = None

class DetectedChange(BaseModel):
    id: int | None = None
    competitor_id: int
    source_type: str
    url: str | None = None
    previous_snapshot_id: int | None = None
    current_snapshot_id: int | None = None
    diff_text: str
    change_summary: str | None = None
    is_processed: bool = False

class Signal(BaseModel):
    id: int | None = None
    change_id: int | None = None
    competitor_id: int
    signal_type: str
    signal_data: dict
    confidence: float = 0.5

class Analysis(BaseModel):
    id: int | None = None
    competitor_id: int
    signal_ids: list[int]
    analysis_text: str
    strategic_implications: list[str] | None = None
    model_used: str | None = None
    tokens_used: int | None = None
```

The `Literal["jobs", "website", "github", "news"]` annotation on `source_type` means Pydantic will reject any value that is not one of those four strings. This catches typos at runtime.

### Step 10 — Write `config/settings.py`

```python
import os
from pathlib import Path
from dotenv import load_dotenv

# load_dotenv() reads the .env file and sets os.environ entries
load_dotenv()

ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
GITHUB_TOKEN: str | None = os.getenv("GITHUB_TOKEN")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

MODEL_ID: str = "claude-sonnet-4-6"
MAX_TOKENS: int = 4096

BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "intelligence.db"
LOG_PATH = BASE_DIR / "logs" / "agent.log"

SCRAPE_TIMEOUT_SECONDS: int = 30
SIMILARITY_THRESHOLD: float = 0.98  # changes below this ratio are ignored as noise
```

Using `os.environ["KEY"]` (square brackets) rather than `os.getenv("KEY")` for required keys means the program crashes immediately with a clear `KeyError` if the key is missing — better than a confusing error deep in the code later.

### Step 11 — Write `config/competitors.py`

```python
from database.models import CompetitorConfig

COMPETITORS: list[CompetitorConfig] = [
    CompetitorConfig(
        name="Razorpay",
        slug="razorpay",
        website_url="https://razorpay.com",
        careers_url="https://razorpay.com/jobs/",
        github_org="razorpay",
        news_query="Razorpay product launch OR funding OR partnership",
    ),
    CompetitorConfig(
        name="Zepto",
        slug="zepto",
        website_url="https://www.zeptonow.com",
        careers_url="https://www.zeptonow.com/careers",
        github_org=None,
        news_query="Zepto quick commerce OR funding OR expansion OR dark store",
    ),
    CompetitorConfig(
        name="PhonePe",
        slug="phonepe",
        website_url="https://www.phonepe.com",
        careers_url="https://careers.phonepe.com",
        github_org="PhonePe",
        news_query="PhonePe UPI OR product OR acquisition OR partnership",
    ),
    CompetitorConfig(
        name="Meesho",
        slug="meesho",
        website_url="https://meesho.com",
        careers_url="https://meesho.com/jobs",
        github_org="Meesho",
        news_query="Meesho social commerce OR funding OR new feature OR seller",
    ),
]
```

---

## Phase 2 — Web Scraping Layer

### What is web scraping?

Web scraping is programmatically fetching web pages and extracting structured data from their HTML. Most modern websites render their content using JavaScript — a plain HTTP GET request returns an empty skeleton, and the actual content loads afterward via JavaScript API calls. That is why we need two types of scrapers:

1. **`httpx` + `BeautifulSoup`** for static pages where the HTML contains the content.
2. **Playwright** for JavaScript-rendered pages — it actually launches a browser, waits for JS to finish rendering, then reads the fully-rendered DOM.

### Step 12 — Write `scrapers/base.py`

An **abstract base class (ABC)** is a class that defines an interface but does not implement it. Any class that inherits from it *must* implement the abstract methods or Python raises a `TypeError`. This enforces a consistent interface across all scrapers.

```python
from abc import ABC, abstractmethod
from database.models import CompetitorConfig, PageSnapshot
import re

class BaseScraper(ABC):
    def __init__(self, competitor: CompetitorConfig):
        self.competitor = competitor

    @abstractmethod
    async def scrape(self) -> list[PageSnapshot]:
        """Fetch data and return a list of PageSnapshot objects."""
        ...

    def _clean_text(self, raw: str) -> str:
        """Normalize whitespace — collapse multiple spaces/newlines into one."""
        text = re.sub(r"[ \t]+", " ", raw)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
```

The `async def scrape()` signature means all scrapers are **asynchronous**. Python's `asyncio` allows you to run multiple async functions concurrently on a single thread using an event loop — when one scraper is waiting for a network response, another can run. This is critical for efficiently scraping four competitors without waiting for each to finish sequentially.

### Step 13 — Write `scrapers/news_scraper.py` (simplest — start here)

Google News provides a free RSS feed that requires no API key. RSS (Really Simple Syndication) is an XML format for content feeds.

URL format:
```
https://news.google.com/rss/search?q=Razorpay+funding+OR+product&hl=en-IN&gl=IN&ceid=IN:en
```

```python
import httpx
from bs4 import BeautifulSoup
from tenacity import retry, wait_exponential, stop_after_attempt
from scrapers.base import BaseScraper
from database.models import PageSnapshot
from detection.hasher import compute_hash

class NewsScraper(BaseScraper):

    @retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(3))
    async def scrape(self) -> list[PageSnapshot]:
        if not self.competitor.news_query:
            return []

        query = self.competitor.news_query.replace(" ", "+")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()  # raises an exception for 4xx/5xx HTTP status codes

        # Parse RSS XML. "lxml-xml" is the XML parser mode of lxml.
        soup = BeautifulSoup(response.content, "lxml-xml")
        items = soup.find_all("item")[:10]  # take the 10 most recent

        lines = []
        for item in items:
            title = item.find("title").get_text(strip=True) if item.find("title") else ""
            pub_date = item.find("pubDate").get_text(strip=True) if item.find("pubDate") else ""
            source = item.find("source").get_text(strip=True) if item.find("source") else ""
            lines.append(f"{pub_date} | {source} | {title}")

        content_text = self._clean_text("\n".join(lines))

        return [PageSnapshot(
            competitor_id=self.competitor.id,
            source_type="news",
            url=url,
            content_hash=compute_hash(content_text),
            content_text=content_text,
        )]
```

**`@retry` decorator from `tenacity`:** This decorator wraps the function and automatically re-runs it if it raises an exception. `wait_exponential(min=2, max=30)` means: wait 2 seconds before retry 1, 4 seconds before retry 2, 8 seconds before retry 3 (doubling each time, capped at 30s). `stop_after_attempt(3)` gives up after 3 total attempts. This makes scrapers resilient to temporary network failures without adding `try/except` boilerplate everywhere.

### Step 14 — Write `scrapers/github_scraper.py`

GitHub's REST API is public for unauthenticated requests up to 60 requests/hour. With a Personal Access Token in the `Authorization` header, it increases to 5,000 requests/hour.

Key API endpoints:
- `GET https://api.github.com/orgs/{org}/repos?sort=updated&per_page=10` — lists recently-updated repos with metadata (star count, language, last push timestamp).
- `GET https://api.github.com/repos/{org}/{repo}/commits?per_page=5` — recent commit messages.

The scraper constructs a human-readable text summary:

```
GitHub activity for razorpay (fetched 2024-06-04):
Repositories (10 most recently updated):
  - razorpay-php [PHP] | 892 stars | last push: 2 days ago
  - blade [TypeScript] | 3,241 stars | last push: 5 hours ago

Recent commits in blade:
  - "feat(Button): add loading state prop"
  - "fix(Modal): close on outside click"
```

This plain-text format is exactly what makes diffing useful — the diff will show clearly when a new repo appears or when the star count changes significantly.

For the implementation: use `httpx.AsyncClient` with headers `{"Authorization": f"token {GITHUB_TOKEN}"}` when `GITHUB_TOKEN` is set. Parse the JSON response and format it into a text block. Use `datetime.fromisoformat()` to compute "N days ago" from the `pushed_at` field.

### Step 15 — Write `scrapers/website_scraper.py`

```python
import httpx
from bs4 import BeautifulSoup
from scrapers.base import BaseScraper
from database.models import PageSnapshot
from detection.hasher import compute_hash
from tenacity import retry, wait_exponential, stop_after_attempt

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

class WebsiteScraper(BaseScraper):

    @retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(3))
    async def scrape(self) -> list[PageSnapshot]:
        if not self.competitor.website_url:
            return []

        url = self.competitor.website_url
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=HEADERS) as client:
            response = await client.get(url)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "lxml")

        # Remove script and style tags — they contain code/CSS, not readable content
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        # Extract all visible text
        text = soup.get_text(separator="\n")
        content_text = self._clean_text(text)

        return [PageSnapshot(
            competitor_id=self.competitor.id,
            source_type="website",
            url=url,
            content_hash=compute_hash(content_text),
            content_text=content_text,
        )]
```

**`soup.decompose()`** removes a tag and its children entirely from the parse tree — cleaner than trying to filter it from the text output.

### Step 16 — Write `scrapers/jobs_scraper.py` (most complex)

**Playwright** is a browser automation library. It starts a real Chromium browser (in headless mode — no visible window), navigates to a URL, waits for JavaScript to finish rendering the page, and then lets you query the fully-rendered DOM.

```python
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from scrapers.base import BaseScraper
from database.models import PageSnapshot
from detection.hasher import compute_hash
from tenacity import retry, wait_exponential, stop_after_attempt
from loguru import logger

class JobsScraper(BaseScraper):

    @retry(wait=wait_exponential(min=5, max=60), stop=stop_after_attempt(3))
    async def scrape(self) -> list[PageSnapshot]:
        if not self.competitor.careers_url:
            return []

        url = self.competitor.careers_url
        job_lines = []

        async with async_playwright() as p:
            # headless=True = no browser window. Set to False for debugging.
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                # goto() navigates and waits for the page to load.
                # "networkidle" waits until there are no more than 0 network
                # connections for at least 500ms — meaning JS has finished loading data.
                await page.goto(url, wait_until="networkidle", timeout=60_000)

                # Try common CSS selectors for job listing containers.
                selectors = [
                    "[data-automation='job-title']",
                    ".job-title", ".jobs-title", ".position-title",
                    "h2.title", "h3.title",
                    "li.job", "div.job", "article.job",
                ]

                for selector in selectors:
                    elements = await page.query_selector_all(selector)
                    if elements:
                        for el in elements:
                            text = await el.inner_text()
                            if text.strip():
                                job_lines.append(text.strip())
                        break

                # Fallback: extract ALL text from the page body
                if not job_lines:
                    body_text = await page.inner_text("body")
                    job_lines = [line.strip() for line in body_text.splitlines() if line.strip()]

            except PlaywrightTimeout:
                logger.warning(f"Timeout scraping jobs for {self.competitor.slug}")
            finally:
                await browser.close()  # always close the browser, even on error

        content_text = self._clean_text("\n".join(job_lines))
        return [PageSnapshot(
            competitor_id=self.competitor.id,
            source_type="jobs",
            url=url,
            content_hash=compute_hash(content_text),
            content_text=content_text,
        )]
```

**`async with async_playwright() as p:`** — The `async with` statement is an **async context manager**. It guarantees cleanup (closing the browser process) even if the code inside raises an exception. The `finally: await browser.close()` is a belt-and-suspenders backup.

---

## Phase 3 — Change Detection Engine

### Why separate rule-based detection from LLM analysis?

Running Claude on every page scrape would be expensive (~$0.003/page × 4 companies × 4 sources × 12 scrapes/day = ~$0.58/day just for unchanged pages). The rule-based engine acts as a **cheap, fast filter** — it only passes *meaningful* changes to Claude, dramatically reducing cost and latency.

### Step 17 — Write `detection/hasher.py`

```python
import hashlib

def compute_hash(text: str) -> str:
    """SHA256 hash of a UTF-8 encoded string. Returns a 64-character hex string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def content_changed(new_text: str, old_hash: str) -> bool:
    """Returns True if new_text has a different SHA256 hash than old_hash."""
    return compute_hash(new_text) != old_hash
```

**SHA256** is a cryptographic hash function. It maps any input string to a fixed 64-character hexadecimal string. Identical inputs always produce identical outputs; even a one-character difference produces a completely different hash. This makes it a perfect "fingerprint" for detecting any change at all.

### Step 18 — Write `detection/differ.py`

```python
import difflib

def generate_diff(old_text: str, new_text: str, context_lines: int = 3) -> str:
    """
    Returns a unified diff between old_text and new_text.
    Lines starting with '+' were added, '-' were removed, ' ' are context.
    context_lines = how many unchanged lines to show around each change (for context).
    """
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff_iter = difflib.unified_diff(
        old_lines, new_lines,
        fromfile="previous",
        tofile="current",
        n=context_lines
    )
    return "".join(diff_iter)

def compute_similarity(old_text: str, new_text: str) -> float:
    """
    Returns a float from 0.0 (completely different) to 1.0 (identical).
    Uses SequenceMatcher which is based on the longest common subsequence algorithm.
    """
    return difflib.SequenceMatcher(None, old_text, new_text).ratio()
```

**`unified_diff` output example:**

```
--- previous
+++ current
@@ -12,7 +12,8 @@
 Senior Backend Engineer - Bangalore
-Senior ML Engineer - Bangalore
+Senior ML Engineer (GenAI) - Bangalore
+Staff ML Engineer - Bangalore
 Product Manager - Mumbai
```

Lines starting with `-` were in the old version but are gone. Lines starting with `+` are new. Lines starting with a space are unchanged context.

### Step 19 — Write `detection/signal_extractor.py`

This is the rule engine. It reads a diff and the source type, then emits typed `Signal` objects.

```python
import re
from database.models import Signal, DetectedChange

ML_KEYWORDS = {"ml", "machine learning", "ai", "artificial intelligence",
               "data scientist", "data engineer", "llm", "nlp", "deep learning"}

def extract_signals(change: DetectedChange, competitor_id: int) -> list[Signal]:
    signals = []
    diff = change.diff_text
    source = change.source_type

    # Lines that start with "+" are additions (but "+++ current" header is excluded)
    added_lines = [l[1:].strip() for l in diff.splitlines()
                   if l.startswith("+") and not l.startswith("+++")]
    removed_lines = [l[1:].strip() for l in diff.splitlines()
                     if l.startswith("-") and not l.startswith("---")]

    if source == "jobs":
        ml_additions = [l for l in added_lines
                        if any(kw in l.lower() for kw in ML_KEYWORDS)]

        if len(ml_additions) >= 3:
            signals.append(Signal(
                change_id=change.id,
                competitor_id=competitor_id,
                signal_type="hiring_surge_ml",
                signal_data={
                    "added_count": len(ml_additions),
                    "roles": ml_additions[:10],
                },
                confidence=0.85,
            ))

        if len(added_lines) >= 8:
            signals.append(Signal(
                change_id=change.id,
                competitor_id=competitor_id,
                signal_type="hiring_surge_general",
                signal_data={
                    "added_count": len(added_lines),
                    "removed_count": len(removed_lines),
                    "sample_roles": added_lines[:5],
                },
                confidence=0.75,
            ))

    elif source == "website":
        price_pattern = re.compile(r"[₹$€]|\d+/month|per month|per year", re.IGNORECASE)
        price_lines = [l for l in added_lines if price_pattern.search(l)]
        if price_lines:
            signals.append(Signal(
                change_id=change.id,
                competitor_id=competitor_id,
                signal_type="pricing_change",
                signal_data={"changed_lines": price_lines[:5]},
                confidence=0.9,
            ))

    elif source == "github":
        repo_pattern = re.compile(r"^\s*-\s+\w[\w\-\.]+\s*\[")
        new_repos = [l for l in added_lines if repo_pattern.match(l)]
        if new_repos:
            signals.append(Signal(
                change_id=change.id,
                competitor_id=competitor_id,
                signal_type="new_public_repo",
                signal_data={"repos": new_repos},
                confidence=0.95,
            ))

    elif source == "news":
        funding_kw = {"funding", "raises", "series a", "series b", "series c",
                      "seed round", "pre-series", "valuation"}
        ma_kw = {"acqui", "merger", "acquires"}
        for line in added_lines:
            low = line.lower()
            if any(kw in low for kw in funding_kw):
                signals.append(Signal(
                    change_id=change.id,
                    competitor_id=competitor_id,
                    signal_type="funding_news",
                    signal_data={"headline": line},
                    confidence=0.9,
                ))
            elif any(kw in low for kw in ma_kw):
                signals.append(Signal(
                    change_id=change.id,
                    competitor_id=competitor_id,
                    signal_type="ma_news",
                    signal_data={"headline": line},
                    confidence=0.9,
                ))
            else:
                signals.append(Signal(
                    change_id=change.id,
                    competitor_id=competitor_id,
                    signal_type="news_mention",
                    signal_data={"headline": line},
                    confidence=0.7,
                ))

    return signals
```

---

## Phase 4 — The Claude AI Agent

### What is a Claude "tool" (function calling)?

When you make an API call to Claude, you can optionally pass a list of **tool definitions** — JSON schemas describing functions the model can choose to call. Claude does not execute code itself — it reads your tool definitions and, when it decides it needs more information, it responds with a special `tool_use` content block that says *"call this function with these arguments."* Your code receives that response, executes the actual Python function, then sends the result back to Claude. Claude then continues its reasoning.

This is the **agentic loop** — a cycle of reasoning and tool calls that continues until Claude has enough information to give a final answer.

### Step 20 — Write `agent/tools.py`

Tool definitions are Python dictionaries following the Anthropic tool schema format:

```python
GET_COMPETITOR_HISTORY = {
    "name": "get_competitor_history",
    "description": (
        "Retrieves past content snapshots for a competitor's data source. "
        "Use this to understand trends over time — e.g., has hiring been "
        "consistently accelerating, or is this a one-time spike?"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "competitor_slug": {
                "type": "string",
                "description": "The competitor identifier, e.g. 'razorpay'"
            },
            "source_type": {
                "type": "string",
                "enum": ["jobs", "website", "github", "news"],
            },
            "limit": {
                "type": "integer",
                "default": 5,
                "description": "How many past snapshots to return (most recent first)"
            }
        },
        "required": ["competitor_slug", "source_type"]
    }
}

GET_ALL_SIGNALS = {
    "name": "get_all_signals_for_competitor",
    "description": (
        "Returns all recently detected signals for a competitor. "
        "Use this to see the full picture before drawing conclusions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "competitor_slug": {"type": "string"},
            "days_back": {
                "type": "integer",
                "default": 7,
                "description": "How many days of signals to include"
            }
        },
        "required": ["competitor_slug"]
    }
}

COMPARE_COMPETITORS = {
    "name": "compare_competitors",
    "description": (
        "Compares a specific metric between two competitors to identify "
        "relative strategic positioning."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "competitor_slug_a": {"type": "string"},
            "competitor_slug_b": {"type": "string"},
            "metric": {
                "type": "string",
                "enum": ["job_count", "github_activity", "news_volume"]
            }
        },
        "required": ["competitor_slug_a", "competitor_slug_b", "metric"]
    }
}

SAVE_ANALYSIS = {
    "name": "save_analysis",
    "description": (
        "Saves the completed strategic analysis to persistent storage. "
        "Call this ONCE at the end, after your reasoning is complete."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "competitor_slug": {"type": "string"},
            "analysis_markdown": {
                "type": "string",
                "description": "Full analysis in markdown format"
            },
            "key_implications": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3 to 5 bullet-point strategic implications"
            }
        },
        "required": ["competitor_slug", "analysis_markdown", "key_implications"]
    }
}

ALL_TOOLS = [GET_COMPETITOR_HISTORY, GET_ALL_SIGNALS, COMPARE_COMPETITORS, SAVE_ANALYSIS]
```

**Why write these as Python dicts rather than Pydantic models?** Because the Anthropic Python SDK expects raw dicts (it serializes them to JSON internally). Wrapping them in Pydantic would add conversion overhead for no gain here.

### Step 21 — Write `agent/tool_executor.py`

```python
import json
from database import db

def handle_get_history(competitor_slug: str, source_type: str, limit: int = 5) -> dict:
    competitor = db.get_competitor_by_slug(competitor_slug)
    if not competitor:
        return {"error": f"Unknown competitor: {competitor_slug}"}

    snapshots = db.get_snapshots(competitor["id"], source_type, limit=limit)
    return {
        "competitor": competitor_slug,
        "source_type": source_type,
        "snapshots": [
            {
                "scraped_at": s["scraped_at"],
                "content_preview": s["content_text"][:500] + "..."
                    if len(s["content_text"]) > 500 else s["content_text"]
            }
            for s in snapshots
        ]
    }

def handle_get_signals(competitor_slug: str, days_back: int = 7) -> dict:
    competitor = db.get_competitor_by_slug(competitor_slug)
    if not competitor:
        return {"error": f"Unknown competitor: {competitor_slug}"}
    signals = db.get_unprocessed_signals(competitor["id"], days_back=days_back)
    return {"competitor": competitor_slug, "signals": [dict(s) for s in signals]}

def handle_compare(competitor_slug_a: str, competitor_slug_b: str, metric: str) -> dict:
    # Query DB for both competitors, compute the metric, return structured comparison
    comp_a = db.get_competitor_by_slug(competitor_slug_a)
    comp_b = db.get_competitor_by_slug(competitor_slug_b)
    if not comp_a or not comp_b:
        return {"error": "One or both competitors not found"}
    # Implementation: query page_snapshots, count/compare based on metric
    return {"metric": metric, "comparison": f"TODO: implement {metric} comparison"}

def handle_save_analysis(competitor_slug: str, analysis_markdown: str,
                         key_implications: list) -> dict:
    competitor = db.get_competitor_by_slug(competitor_slug)
    if not competitor:
        return {"error": f"Unknown competitor: {competitor_slug}"}
    from database.models import Analysis
    analysis = Analysis(
        competitor_id=competitor["id"],
        signal_ids=[],  # populated by analyst.py before calling this
        analysis_text=analysis_markdown,
        strategic_implications=key_implications,
        model_used="claude-sonnet-4-6",
    )
    db.insert_analysis(analysis)
    return {"status": "saved", "competitor": competitor_slug}

TOOL_HANDLERS = {
    "get_competitor_history": handle_get_history,
    "get_all_signals_for_competitor": handle_get_signals,
    "compare_competitors": handle_compare,
    "save_analysis": handle_save_analysis,
}

def execute_tool(tool_name: str, tool_input: dict) -> str:
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    result = handler(**tool_input)
    return json.dumps(result, default=str)
```

`default=str` in `json.dumps` means: if a value is not JSON-serializable (e.g., a `datetime` object), convert it to a string instead of raising an error.

### Step 22 — Write `agent/analyst.py` — the agentic loop

This is the most important file in the project. Study this loop carefully.

```python
import anthropic
from loguru import logger
from agent.tools import ALL_TOOLS
from agent.tool_executor import execute_tool
from database import db
from config.settings import ANTHROPIC_API_KEY, MODEL_ID, MAX_TOKENS

SYSTEM_PROMPT = """You are a competitive intelligence analyst specializing in Indian tech companies.
You have access to real-time signals about competitors: hiring patterns, website changes,
GitHub activity, and press coverage.

Your task: analyze signals for the given company, use your tools to gather historical
context, and produce a strategic intelligence report.

Reason in 4 layers:
1. WHAT CHANGED — What do the signals actually show? Be specific, reference data points.
2. WHAT IT MEANS — What capability or strategic direction does this reveal?
3. WHAT'S NEXT — What will this company likely do in the next 30-90 days based on these signals?
4. WHAT TO DO — What concrete action should a competitor take in response?

Be concise. Avoid vague statements. Reference actual data points.
Call get_competitor_history to check if this is a new trend or a continuation.
End by calling save_analysis with your final markdown report."""


async def analyze_competitor(competitor_slug: str, signal_ids: list[int]) -> str | None:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    competitor = db.get_competitor_by_slug(competitor_slug)
    if not competitor:
        logger.error(f"Competitor not found: {competitor_slug}")
        return None

    signals = db.get_signals_by_ids(signal_ids)
    if not signals:
        return None

    signal_lines = []
    for s in signals:
        import json as _json
        data = _json.loads(s["signal_data"]) if isinstance(s["signal_data"], str) else s["signal_data"]
        signal_lines.append(
            f"- [{s['signal_type']}] (confidence: {s['confidence']:.0%}) | {s['detected_at']}\n"
            f"  Data: {_json.dumps(data, ensure_ascii=False)}"
        )

    user_message = (
        f"Here are the latest signals for {competitor['name']}:\n\n"
        + "\n".join(signal_lines)
        + "\n\nPlease analyze these signals and produce a strategic intelligence report."
    )

    messages = [{"role": "user", "content": user_message}]

    # ── THE AGENTIC LOOP ──────────────────────────────────────────────────────
    while True:
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=ALL_TOOLS,
            messages=messages,
        )

        logger.debug(f"Claude stop_reason={response.stop_reason}")

        # Append Claude's response to conversation history.
        # The API is stateless — we must send the full history on every call.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            # Claude is done — extract the final text block
            for block in response.content:
                if hasattr(block, "text"):
                    db.mark_signals_processed(signal_ids)
                    return block.text
            return None

        if response.stop_reason == "tool_use":
            # Claude wants to call one or more tools
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info(f"Tool call: {block.name}({block.input})")
                    result_str = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,   # must match the tool_use block's ID
                        "content": result_str,
                    })

            # Add tool results as the next user turn, then loop back
            messages.append({"role": "user", "content": tool_results})
    # ── END AGENTIC LOOP ──────────────────────────────────────────────────────
```

**Why `messages.append({"role": "assistant", "content": response.content})`?**

Claude's API is **stateless** — it has no memory of past exchanges. Every call receives the full conversation history in the `messages` list. By appending each response to `messages`, we rebuild the conversation context so Claude can reference what it said and what tools it called in previous turns.

---

## Phase 5 — Scheduler

### What is APScheduler?

**APScheduler** (Advanced Python Scheduler) runs Python functions on a schedule — like cron but in-process. It supports cron-style triggers (`hour='*/2'`), interval triggers (every N minutes), and date triggers (once at a specific datetime). The `BackgroundScheduler` runs on a background thread so your main thread stays free.

### Step 23 — Write `scheduler/jobs.py`

```python
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

IST = pytz.timezone("Asia/Kolkata")


def _run_scraper_job(scraper_class, source_type: str):
    """Generic: runs one scraper class for all active competitors."""
    start = time.time()
    for comp in COMPETITORS:
        if not comp.is_active:
            continue
        try:
            # APScheduler runs jobs in threads, not async context.
            # Create a new event loop per thread to run async scrapers.
            loop = asyncio.new_event_loop()
            scraper = scraper_class(comp)
            snapshots = loop.run_until_complete(scraper.scrape())
            loop.close()

            for snapshot in snapshots:
                _process_snapshot(snapshot, comp)

            db.log_run(source_type, comp.slug, "success", time.time() - start)

        except Exception as e:
            logger.exception(f"Scrape failed: {source_type} / {comp.slug}: {e}")
            db.log_run(source_type, comp.slug, "failed", time.time() - start, str(e))


def _process_snapshot(snapshot, comp):
    """Store snapshot and run change detection against the previous one."""
    previous = db.get_latest_snapshot(comp.id, snapshot.source_type, snapshot.url)

    if previous and not content_changed(snapshot.content_text, previous["content_hash"]):
        logger.debug(f"No change: {comp.slug} / {snapshot.source_type}")
        return  # O(1) hash check — nothing changed

    new_id = db.insert_snapshot(snapshot)

    if not previous:
        logger.info(f"First snapshot stored: {comp.slug} / {snapshot.source_type}")
        return

    similarity = compute_similarity(snapshot.content_text, previous["content_text"])
    if similarity > SIMILARITY_THRESHOLD:
        logger.debug(f"Minor change ({similarity:.1%}): {comp.slug} / {snapshot.source_type}")
        return

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
    change.id = change_id

    signals = extract_signals(change, comp.id)
    for signal in signals:
        db.insert_signal(signal)
        logger.info(f"Signal [{signal.signal_type}] for {comp.slug}")


def scrape_news():     _run_scraper_job(NewsScraper, "news")
def scrape_github():   _run_scraper_job(GithubScraper, "github")
def scrape_jobs():     _run_scraper_job(JobsScraper, "jobs")
def scrape_websites(): _run_scraper_job(WebsiteScraper, "website")


def run_analysis():
    from agent.analyst import analyze_competitor
    for comp in COMPETITORS:
        if not comp.is_active or not comp.id:
            continue
        signals = db.get_unprocessed_signals(comp.id, days_back=7)
        if not signals:
            continue
        signal_ids = [s["id"] for s in signals]
        logger.info(f"Running analysis for {comp.slug} ({len(signal_ids)} signals)")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(analyze_competitor(comp.slug, signal_ids))
        loop.close()


def daily_report():
    from reports.reporter import generate_daily_report
    generate_daily_report()


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=IST)
    scheduler.add_job(scrape_news,     CronTrigger(minute=0))           # every hour
    scheduler.add_job(scrape_github,   CronTrigger(hour="*/2"))         # every 2 hours
    scheduler.add_job(scrape_jobs,     CronTrigger(hour="*/4"))         # every 4 hours
    scheduler.add_job(scrape_websites, CronTrigger(hour="*/6"))         # every 6 hours
    scheduler.add_job(run_analysis,    CronTrigger(hour="6,12,18,0"))   # 4x/day IST
    scheduler.add_job(daily_report,    CronTrigger(hour=8, minute=0))   # 8 AM IST
    return scheduler
```

**`asyncio.new_event_loop()`**: APScheduler runs jobs in threads, not in an async context. To run `async` functions from a thread, you create a new event loop, run the coroutine synchronously with `loop.run_until_complete()`, then close the loop. Each thread gets its own event loop.

---

## Phase 6 — Reports and Entry Point

### Step 24 — Write `reports/reporter.py`

```python
from rich.console import Console
from rich.panel import Panel
from rich import box
from database import db
from pathlib import Path
from config.settings import BASE_DIR
from datetime import datetime, timedelta

console = Console()

def generate_daily_report():
    since = (datetime.now() - timedelta(hours=24)).isoformat()
    analyses = db.get_analyses_since(since)

    if not analyses:
        console.print("[yellow]No analyses in the past 24 hours.[/yellow]")
        return

    report_lines = [f"# Daily Intelligence Briefing — {datetime.now().strftime('%Y-%m-%d')}\n"]

    for analysis in analyses:
        competitor_name = analysis["competitor_name"]
        text = analysis["analysis_text"]

        console.print(Panel(
            f"[bold]{competitor_name}[/bold]\n\n{text[:600]}...",
            title=f"[cyan]{competitor_name}[/cyan]",
            border_style="blue",
            box=box.ROUNDED,
        ))

        report_lines.append(f"## {competitor_name}\n\n{text}\n\n---\n")

    report_path = BASE_DIR / "logs" / f"report_{datetime.now().strftime('%Y-%m-%d')}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    console.print(f"\n[green]Report saved to {report_path}[/green]")
```

### Step 25 — Write `main.py`

```python
import time
import signal as os_signal
from loguru import logger
from config.settings import LOG_PATH, LOG_LEVEL
from database.db import initialize_db
from scheduler.jobs import create_scheduler, scrape_news, scrape_github
from config.competitors import COMPETITORS
from database import db

logger.add(LOG_PATH, rotation="1 day", retention="7 days", level=LOG_LEVEL)


def seed_competitors():
    existing = {c["slug"] for c in db.get_all_active_competitors()}
    for comp in COMPETITORS:
        if comp.slug not in existing:
            comp.id = db.insert_competitor(comp)
            logger.info(f"Seeded competitor: {comp.name}")
        else:
            comp.id = db.get_competitor_by_slug(comp.slug)["id"]


def main():
    logger.info("Starting Competitive Intelligence Agent")

    initialize_db()       # creates tables if they don't exist
    seed_competitors()    # populates competitors table from config

    logger.info("Running initial scrape...")
    scrape_news()         # run immediately so you see results now, not hours later
    scrape_github()

    scheduler = create_scheduler()
    scheduler.start()
    logger.success("Scheduler started. Press Ctrl+C to stop.")

    def shutdown(signum, frame):
        logger.info("Shutting down...")
        scheduler.shutdown(wait=False)
        raise SystemExit(0)

    os_signal.signal(os_signal.SIGINT, shutdown)

    while True:
        time.sleep(60)  # keep main thread alive; scheduler runs on background thread


if __name__ == "__main__":
    main()
```

---

## Verification and Testing

### Step V1 — Run the agent

```powershell
python main.py
```

Expected output:
```
INFO | Starting Competitive Intelligence Agent
INFO | Seeded competitor: Razorpay
INFO | Seeded competitor: Zepto
...
INFO | Running initial scrape...
INFO | First snapshot stored: razorpay / news
...
SUCCESS | Scheduler started. Press Ctrl+C to stop.
```

### Step V2 — Verify database entries

```powershell
python -c "
import sqlite3
conn = sqlite3.connect('data/intelligence.db')
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT competitor_id, source_type, scraped_at FROM page_snapshots').fetchall()
for r in rows:
    print(dict(r))
"
```

### Step V3 — Simulate a change to trigger signal detection

```powershell
python -c "
import sqlite3, hashlib
conn = sqlite3.connect('data/intelligence.db')
row = conn.execute(
    'SELECT id, content_text FROM page_snapshots WHERE source_type=? ORDER BY scraped_at DESC LIMIT 1',
    ('news',)
).fetchone()
new_text = row[1] + '\nWed, 04 Jun 2026 | Inc42 | Razorpay raises Series F at 10B valuation'
new_hash = hashlib.sha256(new_text.encode()).hexdigest()
conn.execute('UPDATE page_snapshots SET content_text=?, content_hash=? WHERE id=?',
             (new_text, new_hash, row[0]))
conn.commit()
print('Snapshot modified — run scrape_news() to detect the change.')
"
```

Then trigger the scraper:

```powershell
python -c "from scheduler.jobs import scrape_news; scrape_news()"
```

Check `detected_changes` and `signals` tables — you should see a new change and a `funding_news` signal.

### Step V4 — Trigger Claude analysis

```powershell
python -c "from scheduler.jobs import run_analysis; run_analysis()"
```

Check the `analyses` table and `logs/` for the saved report.

### Step V5 — Check logs

```powershell
Get-Content logs\agent.log -Tail 50
```

---

## Appendix: Key Concepts Summary

| Concept | What it is | Where used |
|---|---|---|
| Virtual environment | Isolated Python package space | Project root (`.venv/`) |
| Pydantic `BaseModel` | Type-validated data class | `database/models.py` |
| Abstract base class | Interface contract for scrapers | `scrapers/base.py` |
| `async`/`await` | Concurrent I/O on a single thread | All scrapers |
| SHA256 hash | Content fingerprint for O(1) change check | `detection/hasher.py` |
| Unified diff | Line-by-line before/after comparison | `detection/differ.py` |
| Agentic loop | Reasoning → tool call → result → repeat | `agent/analyst.py` |
| Tool use (function calling) | Claude calls Python functions for context | `agent/tools.py`, `tool_executor.py` |
| `BackgroundScheduler` | In-process cron jobs on a separate thread | `scheduler/jobs.py` |
| `asyncio.new_event_loop()` | Run async code from a synchronous thread | `scheduler/jobs.py` |
| `.env` / `python-dotenv` | Secrets loaded into environment variables | `config/settings.py` |
| `tenacity` `@retry` | Automatic retry with exponential backoff | All scrapers |
| Repository pattern | All DB access through one module | `database/db.py` |
