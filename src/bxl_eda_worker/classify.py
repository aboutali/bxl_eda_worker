from __future__ import annotations

import re
from functools import lru_cache

from bxl_eda_worker.config import (
    HIGH_FP_KEYWORDS,
    MIDDLE_EAST_KEYWORDS,
    SANCTIONS_KEYWORDS,
    SWISS_RELEVANCE_KEYWORDS,
)
from bxl_eda_worker.models import Item, Topic


def classify(item: Item) -> Item:
    """Annotate topics, regions and swiss_relevance in-place and return the item."""
    haystack = f"{item.title}\n{item.summary}".lower()

    topics: list[Topic] = []
    if _any_match(haystack, SANCTIONS_KEYWORDS):
        topics.append("sanctions")
    if _any_match(haystack, MIDDLE_EAST_KEYWORDS):
        topics.append("middle_east")
    if _any_match(haystack, HIGH_FP_KEYWORDS):
        topics.append("foreign_policy")

    item.topics = topics
    item.regions = sorted(_matched(haystack, MIDDLE_EAST_KEYWORDS))
    item.swiss_relevance = (
        _any_match(haystack, SWISS_RELEVANCE_KEYWORDS) or "sanctions" in topics
    )
    return item


def is_relevant(item: Item) -> bool:
    return bool(item.topics)


def _any_match(haystack: str, needles: frozenset[str] | set[str]) -> bool:
    return _compile(frozenset(needles)).search(haystack) is not None


def _matched(haystack: str, needles: frozenset[str] | set[str]) -> set[str]:
    return {m.group(0) for m in _compile(frozenset(needles)).finditer(haystack)}


@lru_cache(maxsize=None)
def _compile(needles: frozenset[str]) -> re.Pattern[str]:
    # Word-bounded alternation. Sort longest-first so multi-word phrases win
    # over their constituent words, and re-escape special chars.
    parts = sorted((re.escape(n) for n in needles), key=len, reverse=True)
    pattern = r"\b(?:" + "|".join(parts) + r")\b"
    return re.compile(pattern, re.IGNORECASE)
