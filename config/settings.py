import os
from pathlib import Path
from dotenv import load_dotenv

# load_dotenv() scans for a .env file in the current directory (or parent directories)
# and loads each KEY=VALUE line into os.environ. Without this call, os.environ only
# contains system-level variables — not the ones you put in your .env file.
# Alternative: you could pass the key directly in code, but that risks committing secrets to git.
load_dotenv()

# os.environ["KEY"] raises a KeyError immediately if the key is missing.
# This is intentional — it's better to crash on startup with a clear error than to
# run silently and fail deep inside a scraper.
# Alternative: os.getenv("KEY") returns None instead of crashing — use that for OPTIONAL keys.
ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]

# GITHUB_TOKEN is optional — without it, GitHub's API allows 60 requests/hour.
# With a token, the limit is 5,000 requests/hour.
GITHUB_TOKEN: str | None = os.getenv("GITHUB_TOKEN")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

MODEL_ID: str = "claude-sonnet-4-6"
MAX_TOKENS: int = 4096  # maximum tokens Claude can write in its response

# Path(__file__) is the absolute path to THIS file (settings.py).
# .parent gives the config/ folder, .parent.parent gives the project root.
# This makes paths work regardless of where you run the script from.
# Alternative: os.getcwd() returns the current working directory, which changes
# depending on WHERE you run python from — unreliable.
BASE_DIR = Path(__file__).parent.parent
DB_PATH = BASE_DIR / "data" / "intelligence.db"
LOG_PATH = BASE_DIR / "logs" / "agent.log"

SCRAPE_TIMEOUT_SECONDS: int = 30
# Pages that are 98%+ similar to the last snapshot are treated as "no meaningful change"
# and skipped — avoids noise from minor date/timestamp updates on pages.
SIMILARITY_THRESHOLD: float = 0.98
