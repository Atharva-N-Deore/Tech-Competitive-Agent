# Competitive Intelligence Agent

Monitors Indian tech companies (Razorpay, Zepto, PhonePe, Meesho) — scrapes their websites, job postings, press releases, and GitHub repos on a schedule. Detects signals like "they just hired 10 ML engineers" or "their pricing page changed" and uses an LLM to summarize strategic implications.

Works with any model: Anthropic Claude, OpenAI GPT, local models via Ollama, Groq, and more — swap providers by changing one line in your `.env`.

**Learning objectives:** scheduled agents, web scraping, memory with change detection, long-horizon AI reasoning.

---

## Quick Start

See [HOWTORUN.md](HOWTORUN.md) for the full setup guide.

```powershell
python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt && playwright install chromium
# copy .env.example → .env, set MODEL_ID and the matching API key
python main.py
```

---

## How the System Works

```
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 1 — STARTUP                                                   │
│                                                                     │
│  main.py                                                            │
│    │  ① initialize_db()   ──→  database/schema.sql                  │
│    │  ② seed_competitors() ──→  config/competitors.py               │
│    │                            database/models.py  (data shapes)   │
│    │  ③ create_scheduler() ──→  scheduler/jobs.py                   │
│    └─ scheduler.start()                                             │
└────────────────────────────┬────────────────────────────────────────┘
                             │  every N hours, APScheduler fires a job
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 2 — SCRAPING  (one of these runs on schedule)                 │
│                                                                     │
│  scheduler/jobs.py  _run_scraper_job()                              │
│    │                                                                │
│    ├── NewsScraper    (httpx + BeautifulSoup + Google News RSS)     │
│    ├── GithubScraper  (httpx + GitHub REST API)                     │
│    ├── WebsiteScraper (httpx + BeautifulSoup)                       │
│    └── JobsScraper    (Playwright — headless Chromium browser)      │
│         │                                                           │
│         │  All inherit from scrapers/base.py (abstract interface)   │
│         │  All return a list[PageSnapshot] (database/models.py)     │
│         ▼                                                           │
│    _process_snapshot(snapshot, competitor)                          │
└────────────────────────────┬────────────────────────────────────────┘
                             │  each snapshot goes through change detection
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 3 — CHANGE DETECTION                                          │
│                                                                     │
│  detection/hasher.py                                                │
│    compute_hash(new_text)  ──→  compare to stored hash              │
│    if EQUAL: stop here (no change)                                  │
│    if DIFFERENT: continue ↓                                         │
│                                                                     │
│  database/db.py  insert_snapshot()  ──→  save new snapshot          │
│                                                                     │
│  detection/differ.py                                                │
│    compute_similarity()  ──→  if >98% similar: stop (noise)         │
│    generate_diff()       ──→  unified diff string                   │
│                                                                     │
│  database/db.py  insert_change()   ──→  save the diff               │
│                                                                     │
│  detection/signal_extractor.py                                      │
│    extract_signals(change)  ──→  rule-based typing                  │
│      "hiring_surge_ml", "pricing_change", "funding_news", ...       │
│                                                                     │
│  database/db.py  insert_signal()   ──→  save typed signals          │
└────────────────────────────┬────────────────────────────────────────┘
                             │  signals sit in DB until run_analysis job fires
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 4 — AI ANALYSIS  (runs at 6am, 12pm, 6pm, midnight IST)       │
│                                                                     │
│  scheduler/jobs.py  run_analysis()                                  │
│    for each competitor with unprocessed signals:                    │
│      agent/analyst.py  analyze_competitor()                         │
│        │                                                            │
│        │  Build prompt with signals                                 │
│        │  ┌───────────────────────────────────────┐                 │
│        │  │   THE AGENTIC LOOP (while True)       │                 │
│        │  │                                       │                 │
│        │  │  POST messages → LLM API (LiteLLM)   │                 │
│        │  │         │                             │                 │
│        │  │  finish_reason == "tool_calls"?       │                 │
│        │  │    YES → agent/tool_executor.py       │                 │
│        │  │            execute_tool(name, input)  │                 │
│        │  │            → queries database/db.py   │                 │
│        │  │            append result → loop again │                 │
│        │  │         │                             │                 │
│        │  │  finish_reason == "stop"?             │                 │
│        │  │    YES → extract final text → EXIT    │                 │
│        │  └───────────────────────────────────────┘                 │
│        │                                                            │
│        │  LLM calls save_analysis tool                              │
│        └──→ database/db.py  insert_analysis()                       │
└────────────────────────────┬────────────────────────────────────────┘
                             │  every day at 8am IST
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 5 — DAILY REPORT                                              │
│                                                                     │
│  scheduler/jobs.py  daily_report()                                  │
│    reports/reporter.py  generate_daily_report()                     │
│      database/db.py  get_analyses_since(yesterday)                  │
│      rich → pretty terminal output                                  │
│      logs/report_YYYY-MM-DD.md  → saved markdown file               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## File Map

```
main.py                      ← start here (entry point)
config/
  settings.py                ← env vars, paths, constants
  competitors.py             ← which companies to monitor
database/
  schema.sql                 ← DB table definitions
  models.py                  ← Pydantic data shapes (read alongside schema.sql)
  db.py                      ← all database read/write functions
scrapers/
  base.py                    ← abstract interface (read first)
  news_scraper.py            ← simplest — good first scraper to read
  github_scraper.py          ← GitHub REST API
  website_scraper.py         ← httpx + BeautifulSoup
  jobs_scraper.py            ← Playwright (most complex)
detection/
  hasher.py                  ← SHA256 change fingerprinting
  differ.py                  ← unified diff + similarity ratio
  signal_extractor.py        ← rule-based signal typing
agent/
  tools.py                   ← tool definitions (OpenAI JSON Schema format, works with any provider)
  tool_executor.py           ← Python functions the LLM calls
  analyst.py                 ← THE AGENTIC LOOP (most important file)
scheduler/
  jobs.py                    ← APScheduler job definitions
reports/
  reporter.py                ← terminal output + file export
```

---

## Technology Choices

| What | Tool Used | Why This, Not That |
|---|---|---|
| Language | Python 3.11+ | Best ecosystem for scraping + AI |
| LLM routing | LiteLLM | Single interface for 100+ providers — swap models by changing `MODEL_ID` |
| Default model | `anthropic/claude-sonnet-4-6` | Tool use, long context, strong reasoning — but any model works |
| JS-rendered scraping | Playwright | Better than Selenium (faster, async-native) |
| Static scraping | httpx + BeautifulSoup | httpx is async; requests is synchronous |
| Database | SQLite | No server needed; perfect for local agent |
| Data validation | Pydantic | Runtime type checking; better than dataclasses |
| Scheduling | APScheduler | In-process cron; no separate daemon needed |
| Logging | loguru | Simple API vs. verbose built-in logging |
| Retries | tenacity | Clean decorator vs. manual try/except loops |
