# Pydantic is a data validation library. A class that inherits from BaseModel gets:
#   - automatic type checking (raises ValidationError if you pass the wrong type)
#   - easy conversion to/from dicts and JSON
#   - IDE autocomplete for all fields
# Alternatives: Python dataclasses (no validation), TypedDict (just type hints, no runtime check),
# attrs (similar to Pydantic but older). Pydantic is the industry standard for data contracts.
from pydantic import BaseModel
from typing import Literal
from datetime import datetime


# Represents one row in the `competitors` table.
# id is Optional because it's None before the DB assigns an AUTOINCREMENT value.
class CompetitorConfig(BaseModel):
    id: int | None = None
    name: str
    slug: str
    website_url: str | None = None
    careers_url: str | None = None
    github_org: str | None = None
    news_query: str | None = None
    is_active: bool = True


class PageSnapshot(BaseModel):
    id: int | None = None
    competitor_id: int
    # Literal["a", "b", "c"] means Pydantic will reject any value not in that set.
    # This is like an inline enum — better than a plain str because typos ("jbos") are
    # caught at the point of creation, not later when a query returns no results.
    source_type: Literal["jobs", "website", "github", "news"]
    url: str
    content_hash: str        # SHA256 of content_text — used for fast change detection
    content_text: str        # the actual extracted, cleaned text
    scraped_at: datetime | None = None


# Represents a meaningful diff between two consecutive snapshots.
class DetectedChange(BaseModel):
    id: int | None = None
    competitor_id: int
    source_type: str
    url: str | None = None
    previous_snapshot_id: int | None = None  # FK to page_snapshots
    current_snapshot_id: int | None = None   # FK to page_snapshots
    diff_text: str           # the unified diff string (lines starting with +/-)
    change_summary: str | None = None
    is_processed: bool = False  # True once Claude has analyzed this change


# A typed, structured event extracted from a DetectedChange (by rule-based code, not LLM).
# signal_data is a dict — flexible JSON blob that holds different fields per signal_type.
# e.g., for "hiring_surge_ml": {"added_count": 5, "roles": ["ML Engineer", ...]}
class Signal(BaseModel):
    id: int | None = None
    change_id: int | None = None
    competitor_id: int
    signal_type: str         # e.g. "hiring_surge_ml", "pricing_change", "funding_news"
    signal_data: dict        # varies by signal_type — stored as JSON in the DB
    confidence: float = 0.5  # 0.0 = uncertain, 1.0 = very confident


# Claude's final strategic analysis output for one competitor.
class Analysis(BaseModel):
    id: int | None = None
    competitor_id: int
    signal_ids: list[int]    # which signals were analyzed in this batch
    analysis_text: str       # Claude's full markdown response
    strategic_implications: list[str] | None = None  # extracted bullet points
    model_used: str | None = None
    tokens_used: int | None = None
