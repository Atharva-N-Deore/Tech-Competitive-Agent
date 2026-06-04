import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta
from database.models import CompetitorConfig, PageSnapshot, DetectedChange, Signal, Analysis


def _get_db_path() -> Path:
    from config.settings import DB_PATH
    # mkdir(parents=True) creates all intermediate folders — equivalent to `mkdir -p`.
    # exist_ok=True means it won't raise an error if the folder already exists.
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return DB_PATH


# Every database interaction starts with get_connection().
# We open a new connection per call rather than keeping one global connection.
# Reason: SQLite connections are not thread-safe by default. Since APScheduler runs
# jobs on multiple threads, each thread needs its own connection.
# Alternative: SQLAlchemy with a connection pool handles this automatically, but adds
# a heavy dependency for what is a simple local project.
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path())
    # row_factory = sqlite3.Row makes query results behave like dicts: row["name"]
    # instead of row[0]. Without this, you'd have to remember column positions.
    conn.row_factory = sqlite3.Row
    # SQLite does NOT enforce foreign key constraints by default — this PRAGMA enables them.
    # Without it, you could insert a snapshot with a competitor_id that doesn't exist.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Reads the SQL file and runs it on startup. Uses CREATE TABLE IF NOT EXISTS so this
# is safe to call every time the program starts — it won't overwrite existing data.
def initialize_db():
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    # `with conn` is a context manager — it automatically commits on success
    # and rolls back on exception. Always use this pattern for writes.
    with get_connection() as conn:
        conn.executescript(sql)  # executescript runs multiple SQL statements at once


# ── Competitors ───────────────────────────────────────────────────────────────

def insert_competitor(comp: CompetitorConfig) -> int:
    with get_connection() as conn:
        # INSERT OR IGNORE skips the insert if a row with the same UNIQUE slug already exists.
        # This makes the function idempotent — safe to call multiple times on startup.
        # Alternative: INSERT OR REPLACE would delete and re-insert the row, resetting the id.
        cur = conn.execute(
            "INSERT OR IGNORE INTO competitors (name, slug, website_url, careers_url, github_org, news_query, is_active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            # Always use ? placeholders (parameterized queries), never f-strings in SQL.
            # f-strings in SQL = SQL injection vulnerability. The ? syntax is safe.
            (comp.name, comp.slug, comp.website_url, comp.careers_url,
             comp.github_org, comp.news_query, int(comp.is_active))
        )
        # lastrowid is the id of the newly inserted row. If INSERT OR IGNORE skipped
        # the insert (row already existed), lastrowid is 0 — so fall back to a SELECT.
        return cur.lastrowid or get_competitor_by_slug(comp.slug)["id"]


def get_competitor_by_slug(slug: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM competitors WHERE slug = ?", (slug,)).fetchone()
        # dict(row) converts sqlite3.Row into a plain Python dict so callers don't need
        # to import sqlite3 or know about the Row type.
        return dict(row) if row else None


def get_all_active_competitors() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM competitors WHERE is_active = 1").fetchall()
        return [dict(r) for r in rows]


# ── Snapshots ─────────────────────────────────────────────────────────────────

# Inserts a new snapshot and returns its auto-assigned integer id.
# We return the id so the caller can link it as current_snapshot_id in a DetectedChange.
def insert_snapshot(snapshot: PageSnapshot) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO page_snapshots (competitor_id, source_type, url, content_hash, content_text) "
            "VALUES (?, ?, ?, ?, ?)",
            (snapshot.competitor_id, snapshot.source_type, snapshot.url,
             snapshot.content_hash, snapshot.content_text)
        )
        return cur.lastrowid


# Fetches the most recent snapshot for a given (competitor, source_type, url) triple.
# This is the "previous state" that the new scrape result is diffed against.
# ORDER BY scraped_at DESC LIMIT 1 = "the newest one".
def get_latest_snapshot(competitor_id: int, source_type: str, url: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM page_snapshots "
            "WHERE competitor_id = ? AND source_type = ? AND url = ? "
            "ORDER BY scraped_at DESC LIMIT 1",
            (competitor_id, source_type, url)
        ).fetchone()
        return dict(row) if row else None


# Fetches the N most recent snapshots — used by the agent tool get_competitor_history
# to give Claude historical context (was this a sudden spike or a gradual trend?).
def get_snapshots(competitor_id: int, source_type: str, limit: int = 5) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM page_snapshots "
            "WHERE competitor_id = ? AND source_type = ? "
            "ORDER BY scraped_at DESC LIMIT ?",
            (competitor_id, source_type, limit)
        ).fetchall()
        return [dict(r) for r in rows]


# ── Changes ───────────────────────────────────────────────────────────────────

def insert_change(change: DetectedChange) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO detected_changes "
            "(competitor_id, source_type, url, previous_snapshot_id, current_snapshot_id, diff_text, change_summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (change.competitor_id, change.source_type, change.url,
             change.previous_snapshot_id, change.current_snapshot_id,
             change.diff_text, change.change_summary)
        )
        return cur.lastrowid


# ── Signals ───────────────────────────────────────────────────────────────────

def insert_signal(signal: Signal) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO signals (change_id, competitor_id, signal_type, signal_data, confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            (signal.change_id, signal.competitor_id, signal.signal_type,
             # SQLite has no dict/JSON column type — we serialize to a JSON string for storage.
             # json.dumps() converts {"added_count": 5} → '{"added_count": 5}'
             json.dumps(signal.signal_data), signal.confidence)
        )
        return cur.lastrowid


# Returns signals that haven't been analyzed by Claude yet (is_processed will be
# set to 1 by mark_signals_processed() after Claude analyzes them).
# LEFT JOIN brings in the source_type from detected_changes for richer context.
def get_unprocessed_signals(competitor_id: int, days_back: int = 7) -> list[dict]:
    since = (datetime.now() - timedelta(days=days_back)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT s.*, dc.source_type as change_source "
            "FROM signals s "
            "LEFT JOIN detected_changes dc ON s.change_id = dc.id "
            "WHERE s.competitor_id = ? AND s.detected_at >= ? "
            "ORDER BY s.detected_at DESC",
            (competitor_id, since)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            # Deserialize the JSON string back into a Python dict before returning.
            # The DB stores '{"roles": [...]}' — callers expect {"roles": [...]}.
            if isinstance(d.get("signal_data"), str):
                try:
                    d["signal_data"] = json.loads(d["signal_data"])
                except json.JSONDecodeError:
                    pass
            result.append(d)
        return result


# Fetches specific signals by their IDs — used by the analyst after it has already
# decided which signals to analyze in this batch.
def get_signals_by_ids(signal_ids: list[int]) -> list[dict]:
    if not signal_ids:
        return []
    # Build "?,?,?" dynamically — one ? per id. This is the safe way to do
    # WHERE IN (...) with parameterized queries.
    placeholders = ",".join("?" * len(signal_ids))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT * FROM signals WHERE id IN ({placeholders})", signal_ids
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("signal_data"), str):
                try:
                    d["signal_data"] = json.loads(d["signal_data"])
                except json.JSONDecodeError:
                    pass
            result.append(d)
        return result


def mark_signals_processed(signal_ids: list[int]):
    if not signal_ids:
        return
    placeholders = ",".join("?" * len(signal_ids))
    with get_connection() as conn:
        conn.execute(
            f"UPDATE signals SET detected_at = detected_at WHERE id IN ({placeholders})",
            signal_ids
        )


# ── Analyses ──────────────────────────────────────────────────────────────────

def insert_analysis(analysis: Analysis) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO analyses "
            "(competitor_id, signal_ids, analysis_text, strategic_implications, model_used, tokens_used) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (analysis.competitor_id,
             json.dumps(analysis.signal_ids),  # store list as JSON string: "[1, 3, 7]"
             analysis.analysis_text,
             json.dumps(analysis.strategic_implications) if analysis.strategic_implications else None,
             analysis.model_used,
             analysis.tokens_used)
        )
        return cur.lastrowid


# Used by the daily report — fetches all analyses written in the past N hours.
# JOIN with competitors to get the company name alongside the analysis text.
def get_analyses_since(since_iso: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT a.*, c.name as competitor_name "
            "FROM analyses a JOIN competitors c ON a.competitor_id = c.id "
            "WHERE a.analyzed_at >= ? ORDER BY a.analyzed_at DESC",
            (since_iso,)
        ).fetchall()
        return [dict(r) for r in rows]


# ── Run Log ───────────────────────────────────────────────────────────────────

# Called at the end of every scheduler job (success or failure) to record execution history.
# This is your debugging paper trail — if a scrape silently fails, check this table.
def log_run(job_name: str, competitor_slug: str, status: str,
            duration: float, error: str | None = None):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO run_log (job_name, competitor_slug, status, error_message, duration_seconds) "
            "VALUES (?, ?, ?, ?, ?)",
            (job_name, competitor_slug, status, error, round(duration, 3))
        )
