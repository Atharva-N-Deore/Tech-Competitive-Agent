import os
from pathlib import Path
from dotenv import load_dotenv

# load_dotenv() scans for a .env file in the current directory (or parent directories)
# and loads each KEY=VALUE line into os.environ. Without this call, os.environ only
# contains system-level variables — not the ones you put in your .env file.
# Alternative: you could pass the key directly in code, but that risks committing secrets to git.
load_dotenv()

# All LLM API keys are optional here — LiteLLM reads them from the environment
# automatically by name (ANTHROPIC_API_KEY, OPENAI_API_KEY, GROQ_API_KEY, etc.).
# If you're running a local model via Ollama, no key is needed at all.
ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")

# GITHUB_TOKEN is optional — without it, GitHub's API allows 60 requests/hour.
# With a token, the limit is 5,000 requests/hour.
GITHUB_TOKEN: str | None = os.getenv("GITHUB_TOKEN")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# MODEL_ID uses LiteLLM's "provider/model" format. Examples:
#   anthropic/claude-sonnet-4-6   — Anthropic API (requires ANTHROPIC_API_KEY)
#   gpt-4o                        — OpenAI API (requires OPENAI_API_KEY)
#   groq/llama3-8b-8192           — Groq API (requires GROQ_API_KEY, has free tier)
#   ollama/llama3.2               — local model via Ollama, no key needed
# Set MODEL_ID in your .env file to switch providers without touching code.
MODEL_ID: str = os.getenv("MODEL_ID", "anthropic/claude-sonnet-4-6")
MAX_TOKENS: int = 4096  # maximum tokens the model can write in its response

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
