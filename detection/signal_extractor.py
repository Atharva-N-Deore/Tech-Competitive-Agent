import re
from database.models import Signal, DetectedChange

# Using Python sets ({...}) for keyword lookup instead of lists ([...]).
# set membership check is O(1) — "is 'ml' in this set?" is instant regardless of size.
# list membership check is O(n) — Python scans every element.
# For small lists the difference is tiny, but using sets is a good habit to form.
ML_KEYWORDS = {
    "ml", "machine learning", "ai", "artificial intelligence",
    "data scientist", "data engineer", "llm", "nlp", "deep learning",
    "generative ai", "genai", "computer vision", "mlops",
}

FUNDING_KEYWORDS = {
    "funding", "raises", "raised", "series a", "series b", "series c", "series d",
    "seed round", "pre-series", "valuation", "investor", "investment round",
}

MA_KEYWORDS = {"acqui", "merger", "merges", "acquires", "acquisition"}


# Splits a unified diff into separate "added" and "removed" line lists.
# In a unified diff, lines starting with "+" were added in the new version.
# Lines starting with "+++ current" are the file header — we exclude those.
# l[1:] strips the leading "+" or "-" character, leaving just the content.
def _parse_diff_lines(diff_text: str) -> tuple[list[str], list[str]]:
    added = [l[1:].strip() for l in diff_text.splitlines()
             if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:].strip() for l in diff_text.splitlines()
               if l.startswith("-") and not l.startswith("---")]
    return added, removed


# Main entry point for signal extraction. Routes to a source-specific helper
# based on the change's source_type (jobs, website, github, news).
#
# Why rule-based extraction instead of using Claude for everything?
#   Cost and speed. Running Claude on every page scrape (4 companies × 4 sources × 12 runs/day)
#   would be expensive and slow. Rule-based extraction is instant and free.
#   Claude only runs on signals that have already been filtered and categorized.
#   Think of this as a "pre-processor" that turns raw diffs into structured events.
def extract_signals(change: DetectedChange, competitor_id: int) -> list[Signal]:
    signals: list[Signal] = []
    added, removed = _parse_diff_lines(change.diff_text)

    if change.source_type == "jobs":
        signals.extend(_extract_jobs_signals(change, competitor_id, added, removed))
    elif change.source_type == "website":
        signals.extend(_extract_website_signals(change, competitor_id, added))
    elif change.source_type == "github":
        signals.extend(_extract_github_signals(change, competitor_id, added))
    elif change.source_type == "news":
        signals.extend(_extract_news_signals(change, competitor_id, added))

    return signals


def _extract_jobs_signals(change, competitor_id, added, removed) -> list[Signal]:
    signals = []

    # List comprehension: build a list of added lines that contain at least one ML keyword.
    # any(kw in l.lower() for kw in ML_KEYWORDS) checks all keywords against one line.
    # .lower() ensures case-insensitive matching ("ML Engineer" matches "ml").
    ml_additions = [l for l in added if any(kw in l.lower() for kw in ML_KEYWORDS)]

    # Threshold of 3 ML roles added: chosen to filter noise (1-2 ML roles could be routine
    # backfill), while still catching a genuine buildout. Adjust as needed.
    if len(ml_additions) >= 3:
        signals.append(Signal(
            change_id=change.id,
            competitor_id=competitor_id,
            signal_type="hiring_surge_ml",
            signal_data={"added_count": len(ml_additions), "roles": ml_additions[:10]},
            confidence=0.85,
        ))

    if len(added) >= 8:
        signals.append(Signal(
            change_id=change.id,
            competitor_id=competitor_id,
            signal_type="hiring_surge_general",
            signal_data={
                "added_count": len(added),
                "removed_count": len(removed),
                "sample_roles": added[:5],
            },
            confidence=0.75,
        ))

    if len(removed) >= 8:
        signals.append(Signal(
            change_id=change.id,
            competitor_id=competitor_id,
            signal_type="hiring_slowdown",
            signal_data={"removed_count": len(removed), "sample_roles": removed[:5]},
            confidence=0.70,
        ))

    return signals


def _extract_website_signals(change, competitor_id, added) -> list[Signal]:
    signals = []
    # re.compile() pre-compiles the regex pattern once. More efficient than re.search()
    # inside a loop, which recompiles the pattern on every iteration.
    # [₹$€] matches any currency symbol. \d+\s*/\s*month matches "99/month" or "99 / month".
    price_pattern = re.compile(r"[₹$€]|\d+\s*/\s*month|per\s+month|per\s+year", re.IGNORECASE)
    price_lines = [l for l in added if price_pattern.search(l)]
    if price_lines:
        signals.append(Signal(
            change_id=change.id,
            competitor_id=competitor_id,
            signal_type="pricing_change",
            signal_data={"changed_lines": price_lines[:5]},
            confidence=0.9,
        ))
    return signals


def _extract_github_signals(change, competitor_id, added) -> list[Signal]:
    signals = []
    # The GitHub scraper formats repos as "  - repo-name [Language] | ..."
    # This regex matches that pattern to detect newly added repos.
    # \w[\w\-\.]+ matches repo names like "payments-sdk" or "blade.js".
    repo_pattern = re.compile(r"^\s*-\s+\w[\w\-\.]+\s*\[")
    new_repos = [l for l in added if repo_pattern.match(l)]
    if new_repos:
        signals.append(Signal(
            change_id=change.id,
            competitor_id=competitor_id,
            signal_type="new_public_repo",
            signal_data={"repos": new_repos},
            confidence=0.95,
        ))

    release_kw = {"launch", "release", "v2", "beta", "generally available", "ga release"}
    release_lines = [l for l in added if any(kw in l.lower() for kw in release_kw)]
    if release_lines:
        signals.append(Signal(
            change_id=change.id,
            competitor_id=competitor_id,
            signal_type="product_release_hint",
            signal_data={"lines": release_lines[:5]},
            confidence=0.7,
        ))

    return signals


def _extract_news_signals(change, competitor_id, added) -> list[Signal]:
    signals = []
    for line in added:
        if not line:
            continue
        low = line.lower()
        # Check funding keywords first (more specific), then M&A, then fall back to general mention.
        # This ordering matters: "acquires" would match both MA and general — we want MA to win.
        if any(kw in low for kw in FUNDING_KEYWORDS):
            signals.append(Signal(
                change_id=change.id,
                competitor_id=competitor_id,
                signal_type="funding_news",
                signal_data={"headline": line},
                confidence=0.9,
            ))
        elif any(kw in low for kw in MA_KEYWORDS):
            signals.append(Signal(
                change_id=change.id,
                competitor_id=competitor_id,
                signal_type="ma_news",
                signal_data={"headline": line},
                confidence=0.9,
            ))
        else:
            # Every new news headline is at minimum a "news_mention" signal —
            # Claude can decide whether it's strategically relevant during analysis.
            signals.append(Signal(
                change_id=change.id,
                competitor_id=competitor_id,
                signal_type="news_mention",
                signal_data={"headline": line},
                confidence=0.7,
            ))
    return signals
