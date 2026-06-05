# How to Run the Competitive Intelligence Agent

Everything you need to install, configure, and run the agent from scratch.

---

## Prerequisites

Before starting, make sure you have:

- **Python 3.11 or newer** — check with `python --version`
- **An API key for your chosen model provider** — see the `.env` setup step below for options. If you want to run a local model with Ollama, no key is needed at all.
- *(Optional)* **A GitHub Personal Access Token** — increases GitHub API rate limits from 60 to 5,000 requests/hour

---

## Step-by-Step Setup

### 1. Open a terminal in the project folder

In VS Code: press `` Ctrl+` `` to open the integrated terminal. Make sure the path shown ends in `Competitive Intelligence Agent`.

### 2. Create the virtual environment

```powershell
python -m venv .venv
```

This creates a `.venv/` folder with an isolated Python installation. You only do this once.

### 3. Activate the virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
```

You'll see `(.venv)` appear at the start of your prompt. **You must activate the venv every time you open a new terminal.** If you see `(.venv)` in the prompt, it's active.

> **Troubleshooting:** If PowerShell says "execution of scripts is disabled", run this once:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```
> Then try the activation command again.

### 4. Install Python packages

```powershell
pip install -r requirements.txt
```

This installs all packages listed in `requirements.txt` into your virtual environment. It may take 1-2 minutes.

### 5. Install the Playwright browser

```powershell
playwright install chromium
```

This downloads the Chromium browser binary (~150MB) that `jobs_scraper.py` needs. It's a one-time download stored in Playwright's own cache folder, not in your project.

### 6. Create your `.env` file

Copy the template:
```powershell
Copy-Item .env.example .env
```

Then open `.env`. The two things you must set are **`MODEL_ID`** and the matching API key for that provider.

**Option A — Anthropic Claude (cloud, default)**
```
MODEL_ID=anthropic/claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
```
Get a key: console.anthropic.com → API Keys → Create Key. Copy it immediately — you can't view it again.

**Option B — OpenAI (cloud)**
```
MODEL_ID=gpt-4o
OPENAI_API_KEY=sk-your-key-here
```
Get a key: platform.openai.com → API keys.

**Option C — Groq (cloud, free tier available)**
```
MODEL_ID=groq/llama-3.3-70b-versatile
GROQ_API_KEY=gsk_your-key-here
```
Get a key: console.groq.com → API Keys.

**Option D — Ollama (local, no API key needed)**
```
MODEL_ID=ollama/llama3.2
```
You need [Ollama](https://ollama.com) installed and the model pulled:
```powershell
ollama pull llama3.2
```
Ollama must be running (`ollama serve`) before you start the agent. No internet required after the initial model download.

> **Note on local models and tool use:** Tool calling (function calling) works reliably with large models. Smaller local models (7B parameters or fewer) may struggle to follow tool-use instructions consistently — if analysis looks wrong or tools never get called, try a larger model.

**How to get a GitHub token (optional):**
1. Go to github.com → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click "Generate new token (classic)"
3. Give it a name, set expiry to 90 days, leave ALL permission boxes unchecked (public repos need no permissions)
4. Click "Generate token" and copy it

### 7. Run the agent

```powershell
python main.py
```

---

## What Happens When You Run It

```
============================================================
Starting Competitive Intelligence Agent
============================================================
INFO | Seeded competitor: Razorpay
INFO | Seeded competitor: Zepto
INFO | Seeded competitor: PhonePe
INFO | Seeded competitor: Meesho
INFO | Running initial scrape (news + github)...
INFO | Job: scrape_news
INFO | First snapshot: razorpay/news
INFO | First snapshot: zepto/news
INFO | First snapshot: phonepe/news
INFO | First snapshot: meesho/news
INFO | Job: scrape_github
INFO | First snapshot: razorpay/github
...
SUCCESS | Scheduler started. Monitoring: Razorpay, Zepto, PhonePe, Meesho
INFO | Press Ctrl+C to stop.
```

The agent is now running. It will continue scraping on a schedule until you press Ctrl+C.

**First run:** The first scrape stores baseline snapshots. No changes are detected yet (there's nothing to compare against). After the second run of each scraper, it will start detecting changes.

---

## Scheduler: What Runs and When

| Job | Frequency | What it does |
|---|---|---|
| `scrape_news` | Every hour (at :00) | Fetches Google News RSS for each company |
| `scrape_github` | Every 2 hours | Calls GitHub API for repo activity |
| `scrape_jobs` | Every 4 hours | Opens career pages in headless Chromium |
| `scrape_websites` | Every 6 hours | Fetches homepage text |
| `run_analysis` | 6am, 12pm, 6pm, midnight IST | Sends new signals to the LLM for analysis |
| `daily_report` | 8am IST | Prints and saves a morning digest |

**First analysis:** The agent needs to detect signals (changes) before the LLM can analyze anything. If you're testing the first time, wait for at least two scrape cycles (2+ hours) for changes to appear.

---

## Checking the Database

The SQLite database is at `data/intelligence.db`. You can inspect it with:

```powershell
python -c "
import sqlite3
conn = sqlite3.connect('data/intelligence.db')
conn.row_factory = sqlite3.Row

# Check stored snapshots
print('=== Snapshots ===')
rows = conn.execute('SELECT competitor_id, source_type, scraped_at FROM page_snapshots ORDER BY scraped_at DESC LIMIT 10').fetchall()
for r in rows:
    print(dict(r))

# Check detected changes
print('=== Changes ===')
rows = conn.execute('SELECT competitor_id, source_type, detected_at FROM detected_changes LIMIT 5').fetchall()
for r in rows:
    print(dict(r))

# Check signals
print('=== Signals ===')
rows = conn.execute('SELECT competitor_id, signal_type, confidence FROM signals LIMIT 10').fetchall()
for r in rows:
    print(dict(r))
"
```

---

## Manually Triggering Jobs (for Testing)

You don't have to wait for the scheduler. You can trigger any job immediately:

```powershell
# Run all four scrapers right now
python -c "from scheduler.jobs import scrape_news, scrape_github, scrape_jobs, scrape_websites; scrape_news(); scrape_github()"

# Run just the analysis (LLM)
python -c "from scheduler.jobs import run_analysis; run_analysis()"

# Run the daily report
python -c "from scheduler.jobs import daily_report; daily_report()"
```

---

## Simulating a Change (for Testing Without Waiting)

To see the signal detection and analysis work immediately, inject a fake change into the database:

```powershell
python -c "
import sqlite3, hashlib

conn = sqlite3.connect('data/intelligence.db')

# Get the latest Razorpay news snapshot
row = conn.execute(
    'SELECT id, content_text FROM page_snapshots WHERE source_type=? ORDER BY scraped_at DESC LIMIT 1',
    ('news',)
).fetchone()

if row:
    # Append a fake funding headline
    new_text = row[1] + '\nWed, 04 Jun 2026 | TechCrunch | Razorpay raises Series F at 10B valuation'
    new_hash = hashlib.sha256(new_text.encode()).hexdigest()
    conn.execute(
        'UPDATE page_snapshots SET content_text=?, content_hash=? WHERE id=?',
        (new_text, new_hash, row[0])
    )
    conn.commit()
    print('Done — now run: python -c \"from scheduler.jobs import scrape_news; scrape_news()\"')
else:
    print('No news snapshot found — run scrape_news() first.')
"
```

Then trigger the scraper to detect the change:
```powershell
python -c "from scheduler.jobs import scrape_news; scrape_news()"
```

Then run analysis:
```powershell
python -c "from scheduler.jobs import run_analysis; run_analysis()"
```

---

## Viewing Reports

Reports are saved to `logs/report_YYYY-MM-DD.md`. View today's report:

```powershell
Get-Content "logs\report_$(Get-Date -Format 'yyyy-MM-dd').md"
```

Or trigger the report manually:
```powershell
python -c "from scheduler.jobs import daily_report; daily_report()"
```

---

## Checking Logs

```powershell
# Last 50 lines of the log file
Get-Content logs\agent.log -Tail 50

# Watch logs in real time while the agent runs (in a second terminal)
Get-Content logs\agent.log -Wait -Tail 20
```

---

## Stopping the Agent

Press `Ctrl+C` in the terminal where `python main.py` is running.

---

## Common Errors and Fixes

| Error | Cause | Fix |
|---|---|---|
| `AuthenticationError` or `401` | API key missing or wrong for the chosen provider | Check that `.env` has the correct key for your `MODEL_ID`'s provider |
| `litellm.exceptions.NotFoundError` | `MODEL_ID` is misspelled or unsupported | Check the provider prefix — e.g. `anthropic/`, `groq/`, `ollama/` |
| `Connection refused` with Ollama | Ollama server not running | Run `ollama serve` in a separate terminal |
| `playwright._impl._errors.Error: Executable doesn't exist` | Playwright browser not installed | Run `playwright install chromium` |
| `ModuleNotFoundError: No module named 'litellm'` | Venv not activated or packages not installed | Activate `.venv` then run `pip install -r requirements.txt` |
| `httpx.ConnectError` | No internet connection or site blocked the request | Check your connection; the scraper will retry automatically |
| `sqlite3.OperationalError: no such table` | Database not initialized | This auto-runs on startup — check that `data/` folder exists |
| `No signals found` during analysis | No changes detected yet | Wait for 2+ scrape cycles, or inject a test change (see above) |
| Analysis runs but tool calls never happen | Local model too small to follow tool-use instructions | Switch to a larger model (13B+) or a cloud provider |

---

## Adding a New Competitor

Edit `config/competitors.py` and add a new `CompetitorConfig` entry. The next startup will automatically insert it into the database and begin monitoring it.

```python
CompetitorConfig(
    name="Swiggy",
    slug="swiggy",
    website_url="https://www.swiggy.com",
    careers_url="https://careers.swiggy.com",
    github_org="Swiggy",
    news_query="Swiggy food delivery OR funding OR product launch",
),
```
