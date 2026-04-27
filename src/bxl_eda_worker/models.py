from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Topic = Literal["sanctions", "middle_east", "foreign_policy"]
Region = str


class Item(BaseModel):
    url: str
    source: str        # source id
    category: str = "eu_institution"
    title: str
    summary: str = ""
    language: str = "en"
    published_at: datetime | None = None
    fetched_at: datetime
    topics: list[Topic] = Field(default_factory=list)
    regions: list[Region] = Field(default_factory=list)
    swiss_relevance: bool = False

    # LLM enrichment (set by analyze.py; empty if no key configured)
    summary_oneliner: str = ""
    swiss_rationale: str = ""
    importance: int = 0  # 1–5; 0 means "not enriched"


class ItemEnrichment(BaseModel):
    """Schema for messages.parse() per-item enrichment response."""

    summary_oneliner: str = Field(
        description="One-sentence summary, ≤30 words, no preamble."
    )
    topics: list[Topic] = Field(
        description="Subset of {sanctions, middle_east, foreign_policy}. Empty if none truly apply."
    )
    regions: list[str] = Field(
        description="Lowercase country/region keywords (e.g. 'iran', 'gaza', 'russia'). Empty list if none."
    )
    swiss_relevance: bool = Field(
        description="True if a SECO/EDA/Bundesrat reader needs this on their radar."
    )
    swiss_rationale: str = Field(
        description="One short clause explaining the Swiss angle. Empty string if swiss_relevance is False."
    )
    importance: int = Field(
        ge=1, le=5,
        description="1=routine, 5=front-page-of-FT. Calibrate against EU foreign-policy daily news flow.",
    )
