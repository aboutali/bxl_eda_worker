from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Topic = Literal["sanctions", "middle_east", "foreign_policy"]
Region = str  # e.g. "iran", "gaza", "russia" — free-form, lower-case


class Item(BaseModel):
    url: str
    source: str  # source id, e.g. "eeas_press"
    title: str
    summary: str = ""
    published_at: datetime | None = None
    fetched_at: datetime
    topics: list[Topic] = Field(default_factory=list)
    regions: list[Region] = Field(default_factory=list)
    swiss_relevance: bool = False
