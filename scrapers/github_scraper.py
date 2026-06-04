from datetime import datetime, timezone
import httpx
from tenacity import retry, wait_exponential, stop_after_attempt
from loguru import logger
from scrapers.base import BaseScraper
from database.models import PageSnapshot
from detection.hasher import compute_hash


# Converts GitHub's ISO timestamp ("2024-06-04T10:30:00Z") into a human-readable
# relative string ("2 days ago"). Used to make the snapshot text more diff-friendly.
def _days_ago(iso_str: str) -> str:
    try:
        # GitHub returns timestamps with "Z" suffix (UTC). Python's fromisoformat()
        # doesn't understand "Z" until Python 3.11 — replace it with "+00:00" for compatibility.
        pushed = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - pushed
        days = delta.days
        if days == 0:
            return "today"
        return f"{days} day{'s' if days != 1 else ''} ago"
    except Exception:
        return iso_str  # fall back to raw string if parsing fails


class GithubScraper(BaseScraper):

    @retry(wait=wait_exponential(min=2, max=30), stop=stop_after_attempt(3))
    async def scrape(self) -> list[PageSnapshot]:
        if not self.competitor.github_org:
            return []

        org = self.competitor.github_org
        # "application/vnd.github+json" is GitHub's recommended Accept header for their API v3.
        # It tells the API to use the latest stable response format.
        headers = {"Accept": "application/vnd.github+json"}

        from config.settings import GITHUB_TOKEN
        if GITHUB_TOKEN:
            # Without Authorization: unauthenticated requests are rate-limited to 60/hour.
            # With a Personal Access Token (PAT): 5,000/hour. A PAT requires no special
            # permissions for reading public repos — just create one at github.com/settings/tokens.
            # Alternative: OAuth app tokens — more complex, better for multi-user products.
            headers["Authorization"] = f"token {GITHUB_TOKEN}"

        # We use the REST API directly with httpx rather than the PyGithub library.
        # PyGithub is a Python wrapper around the same API — it's more convenient for
        # complex use cases but adds a dependency and hides what's happening.
        # For learning purposes, raw httpx calls make the API interaction explicit.
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            resp = await client.get(
                f"https://api.github.com/orgs/{org}/repos",
                params={"sort": "updated", "per_page": 10}
            )
            if resp.status_code == 404:
                logger.warning(f"GitHub org not found: {org}")
                return []
            resp.raise_for_status()
            repos = resp.json()  # GitHub API returns JSON — parse it into a Python list of dicts

        # Build a text representation of GitHub activity.
        # We format it as structured text (not raw JSON) so that diffs between runs
        # are human-readable: "star count went from 892 to 1,203" shows as a changed line.
        lines = [f"GitHub activity for {org}:", f"Repositories ({len(repos)} most recently updated):"]

        for repo in repos:
            name = repo.get("name", "")
            lang = repo.get("language") or "unknown"
            stars = repo.get("stargazers_count", 0)
            pushed = _days_ago(repo.get("pushed_at", ""))
            lines.append(f"  - {name} [{lang}] | {stars:,} stars | last push: {pushed}")

        # Fetch recent commit messages for the most-recently-updated repo.
        # Commit messages are strong signals — "feat: add UPI autopay" reveals roadmap direction.
        if repos:
            top_repo = repos[0]["name"]
            async with httpx.AsyncClient(timeout=30, headers=headers) as client:
                cr = await client.get(
                    f"https://api.github.com/repos/{org}/{top_repo}/commits",
                    params={"per_page": 5}
                )
                if cr.status_code == 200:
                    commits = cr.json()
                    lines.append(f"\nRecent commits in {top_repo}:")
                    for c in commits:
                        # Commit messages can be multi-line — take only the first line (the subject).
                        msg = c.get("commit", {}).get("message", "").split("\n")[0]
                        lines.append(f"  - \"{msg}\"")

        content_text = self._clean_text("\n".join(lines))
        url = f"https://api.github.com/orgs/{org}"

        return [PageSnapshot(
            competitor_id=self.competitor.id,
            source_type="github",
            url=url,
            content_hash=compute_hash(content_text),
            content_text=content_text,
        )]
