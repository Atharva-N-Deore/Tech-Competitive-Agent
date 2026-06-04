# Claude's "tool use" (also called "function calling") works like this:
# 1. You define tools as JSON Schema objects and pass them in the API call.
# 2. Claude reads the descriptions and decides if it needs to call a tool.
# 3. If yes, Claude responds with a tool_use content block instead of text.
# 4. YOUR code executes the actual Python function (in tool_executor.py).
# 5. You send the result back to Claude, and it continues reasoning.
#
# Each tool is a plain Python dict — NOT a Pydantic model — because the Anthropic SDK
# expects raw dicts and serializes them to JSON internally. Adding Pydantic here would
# require a conversion step with no benefit.
#
# The "description" field is critical: Claude reads it to decide WHEN to call the tool.
# Write descriptions from Claude's perspective: "use this when you want to..."

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
                "description": "The competitor identifier, e.g. 'razorpay'",
            },
            "source_type": {
                "type": "string",
                # "enum" restricts valid values — Claude cannot pass "Github" or "Jobs" (wrong case).
                # This prevents Claude from hallucinating a value not in our database.
                "enum": ["jobs", "website", "github", "news"],
                "description": "Which data source to look up",
            },
            "limit": {
                "type": "integer",
                "default": 5,
                "description": "How many past snapshots to return (most recent first)",
            },
        },
        # "required" lists fields Claude MUST provide — Claude will not call this tool
        # without supplying these. limit is not required because it has a default.
        "required": ["competitor_slug", "source_type"],
    },
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
                "description": "How many days of signals to include",
            },
        },
        "required": ["competitor_slug"],
    },
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
                "enum": ["job_count", "github_activity", "news_volume"],
            },
        },
        "required": ["competitor_slug_a", "competitor_slug_b", "metric"],
    },
}

# The only "write" tool — all other tools are read-only.
# Having Claude call save_analysis explicitly (rather than auto-saving) gives Claude
# the chance to decide when its analysis is complete. It also forces a structured,
# well-formed output rather than parsing free-form text.
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
                "description": "Full analysis in markdown format",
            },
            "key_implications": {
                "type": "array",
                "items": {"type": "string"},
                "description": "3 to 5 bullet-point strategic implications",
            },
        },
        "required": ["competitor_slug", "analysis_markdown", "key_implications"],
    },
}

# ALL_TOOLS is passed directly to the API call in analyst.py.
# Adding a new tool: define it above, add it to this list. That's all.
ALL_TOOLS = [GET_COMPETITOR_HISTORY, GET_ALL_SIGNALS, COMPARE_COMPETITORS, SAVE_ANALYSIS]
