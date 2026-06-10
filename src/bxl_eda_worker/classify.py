from __future__ import annotations

import re
from functools import lru_cache

from bxl_eda_worker.config import (
    HIGH_FP_KEYWORDS,
    MIDDLE_EAST_KEYWORDS,
    MULTILATERAL_FORUM_KEYWORDS,
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


def is_multilateral_forum_statement(item: Item) -> bool:
    """True for EEAS "EU Statement" interventions delivered in non-EU multilateral
    bodies (IAEA, OSCE, UN…). These are procedural and get relegated to a brief
    aside rather than the main digest.

    Scoped to EEAS-sourced items on purpose: press coverage that merely *mentions*
    the IAEA stays relevant, and EU bodies (Foreign Affairs Council, European
    Council) are not in MULTILATERAL_FORUM_KEYWORDS so they remain in the digest.
    """
    if not item.source.startswith("eeas"):
        return False
    return _any_match(item.title.lower(), MULTILATERAL_FORUM_KEYWORDS)


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
