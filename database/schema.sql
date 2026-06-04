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

CREATE TABLE IF NOT EXISTS page_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id   INTEGER NOT NULL REFERENCES competitors(id),
    source_type     TEXT NOT NULL,
    url             TEXT NOT NULL,
    content_hash    TEXT NOT NULL,
    content_text    TEXT NOT NULL,
    scraped_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_snapshots_lookup
    ON page_snapshots (competitor_id, source_type, url);

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

CREATE TABLE IF NOT EXISTS signals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id      INTEGER REFERENCES detected_changes(id),
    competitor_id  INTEGER NOT NULL REFERENCES competitors(id),
    signal_type    TEXT NOT NULL,
    signal_data    TEXT NOT NULL,
    confidence     REAL NOT NULL DEFAULT 0.5,
    detected_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

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

CREATE TABLE IF NOT EXISTS run_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name         TEXT NOT NULL,
    competitor_slug  TEXT,
    status           TEXT NOT NULL,
    error_message    TEXT,
    duration_seconds REAL,
    ran_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
