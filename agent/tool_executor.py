import json
from database import db


# Each handle_* function corresponds to one tool defined in tools.py.
# They receive exactly the arguments Claude passed in tool_input, execute a DB query,
# and return a Python dict. The dict is serialized to a JSON string before being
# sent back to Claude — Claude can only receive text in tool results, not Python objects.

def handle_get_history(competitor_slug: str, source_type: str, limit: int = 5) -> dict:
    competitor = db.get_competitor_by_slug(competitor_slug)
    if not competitor:
        return {"error": f"Unknown competitor: {competitor_slug}"}

    snapshots = db.get_snapshots(competitor["id"], source_type, limit=limit)
    return {
        "competitor": competitor_slug,
        "source_type": source_type,
        "snapshot_count": len(snapshots),
        "snapshots": [
            {
                "scraped_at": s["scraped_at"],
                # Truncate to 500 characters — Claude's context window has limited space.
                # Sending the full 10,000-character snapshot for each of 5 history entries
                # would consume most of the available context.
                "content_preview": (
                    s["content_text"][:500] + "..."
                    if len(s["content_text"]) > 500
                    else s["content_text"]
                ),
            }
            for s in snapshots
        ],
    }


def handle_get_signals(competitor_slug: str, days_back: int = 7) -> dict:
    competitor = db.get_competitor_by_slug(competitor_slug)
    if not competitor:
        return {"error": f"Unknown competitor: {competitor_slug}"}

    signals = db.get_unprocessed_signals(competitor["id"], days_back=days_back)
    return {
        "competitor": competitor_slug,
        "signal_count": len(signals),
        "signals": [
            {
                "id": s["id"],
                "signal_type": s["signal_type"],
                "confidence": s["confidence"],
                "detected_at": s["detected_at"],
                "signal_data": s["signal_data"],
            }
            for s in signals
        ],
    }


def handle_compare(competitor_slug_a: str, competitor_slug_b: str, metric: str) -> dict:
    comp_a = db.get_competitor_by_slug(competitor_slug_a)
    comp_b = db.get_competitor_by_slug(competitor_slug_b)
    if not comp_a or not comp_b:
        return {"error": "One or both competitors not found"}

    if metric == "job_count":
        snaps_a = db.get_snapshots(comp_a["id"], "jobs", limit=1)
        snaps_b = db.get_snapshots(comp_b["id"], "jobs", limit=1)
        # Approximation: count lines in the jobs snapshot as a proxy for job count.
        # Real job counts would require parsing structured job data from each scraper.
        count_a = len(snaps_a[0]["content_text"].splitlines()) if snaps_a else 0
        count_b = len(snaps_b[0]["content_text"].splitlines()) if snaps_b else 0
        return {
            "metric": "job_count",
            competitor_slug_a: count_a,
            competitor_slug_b: count_b,
            "note": "Approximate job count based on line count of latest jobs snapshot",
        }

    if metric == "news_volume":
        from datetime import datetime, timedelta
        sigs_a = db.get_unprocessed_signals(comp_a["id"], days_back=30)
        sigs_b = db.get_unprocessed_signals(comp_b["id"], days_back=30)
        news_a = [s for s in sigs_a if "news" in s.get("signal_type", "")]
        news_b = [s for s in sigs_b if "news" in s.get("signal_type", "")]
        return {
            "metric": "news_volume",
            competitor_slug_a: len(news_a),
            competitor_slug_b: len(news_b),
        }

    return {"metric": metric, "note": f"Metric '{metric}' comparison not fully implemented yet"}


def handle_save_analysis(competitor_slug: str, analysis_markdown: str,
                         key_implications: list) -> dict:
    competitor = db.get_competitor_by_slug(competitor_slug)
    if not competitor:
        return {"error": f"Unknown competitor: {competitor_slug}"}

    from database.models import Analysis
    from config.settings import MODEL_ID

    analysis = Analysis(
        competitor_id=competitor["id"],
        signal_ids=[],           # populated by analyst.py in a future improvement
        analysis_text=analysis_markdown,
        strategic_implications=key_implications,
        model_used=MODEL_ID,
    )
    analysis_id = db.insert_analysis(analysis)
    return {"status": "saved", "analysis_id": analysis_id, "competitor": competitor_slug}


# Dispatch table: maps tool name strings to handler functions.
# Alternative: a giant if/elif chain — works but is harder to extend.
# With a dict, adding a new tool = add one line here + define the function above.
TOOL_HANDLERS = {
    "get_competitor_history": handle_get_history,
    "get_all_signals_for_competitor": handle_get_signals,
    "compare_competitors": handle_compare,
    "save_analysis": handle_save_analysis,
}


# Single entry point called by the agentic loop in analyst.py.
# Looks up the handler, calls it with Claude's arguments, and returns a JSON string.
# Returns a JSON string (not a dict) because Claude's tool_result content must be text.
def execute_tool(tool_name: str, tool_input: dict) -> str:
    handler = TOOL_HANDLERS.get(tool_name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        result = handler(**tool_input)  # ** unpacks the dict as keyword arguments
    except Exception as e:
        result = {"error": str(e)}
    # default=str: if any value in result is not JSON-serializable (e.g., a datetime object),
    # convert it to its string representation instead of raising a TypeError.
    return json.dumps(result, default=str)
