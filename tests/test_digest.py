from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bxl_eda_worker.config import Source
from bxl_eda_worker.digest import render
from bxl_eda_worker.models import Item


def _src(id: str, category: str, weight: int = 2, badge: str = "") -> Source:
    return Source(
        id=id,
        name=f"Source {id}",
        type="rss",
        url="https://example.test",
        category=category,
        weight=weight,
        badge=badge,
    )


def _item(url: str, source: str, category: str, title: str, **overrides) -> Item:
    base = dict(
        url=url,
        source=source,
        category=category,
        title=title,
        language="en",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
        topics=["foreign_policy"],
        regions=[],
        swiss_relevance=False,
    )
    base.update(overrides)
    return Item(**base)


def test_swiss_official_section_appears_above_eu():
    sources = [
        _src("seco", "swiss_official"),
        _src("eeas", "eu_institution"),
    ]
    items = [
        _item("https://t/1", "seco", "swiss_official", "SECO updates sanctions list",
              topics=["sanctions"], swiss_relevance=True),
        _item("https://t/2", "eeas", "eu_institution", "HR/VP Kallas issues statement",
              topics=["foreign_policy"]),
    ]
    out = render(items, sources,
                 window_start=datetime.now(timezone.utc) - timedelta(hours=24),
                 window_end=datetime.now(timezone.utc))
    swiss_idx = out.find("🇨🇭 Swiss confederation")
    eu_idx = out.find("🇪🇺 EU institutions")
    assert 0 < swiss_idx < eu_idx, "Swiss section must precede EU section"


def test_swiss_relevance_highlights_appear_first():
    sources = [_src("eeas", "eu_institution")]
    items = [
        _item("https://t/1", "eeas", "eu_institution", "Sanctions package",
              topics=["sanctions"], swiss_relevance=True),
    ]
    out = render(items, sources,
                 window_start=datetime.now(timezone.utc) - timedelta(hours=24),
                 window_end=datetime.now(timezone.utc))
    highlights_idx = out.find("Swiss-relevance highlights")
    eu_section_idx = out.find("🇪🇺 EU institutions")
    assert 0 < highlights_idx < eu_section_idx


def test_badge_renders_next_to_source_name():
    sources = [_src("council", "eu_institution", badge="FAC")]
    items = [_item("https://t/1", "council", "eu_institution",
                   "Foreign Affairs Council adopts conclusions",
                   topics=["foreign_policy"])]
    out = render(items, sources,
                 window_start=datetime.now(timezone.utc) - timedelta(hours=24),
                 window_end=datetime.now(timezone.utc))
    assert "Source council FAC" in out


def test_non_english_language_marker():
    sources = [_src("nzz", "press_swiss")]
    items = [_item("https://t/1", "nzz", "press_swiss",
                   "EU verhängt neue Sanktionen", language="de",
                   topics=["sanctions"], swiss_relevance=True)]
    out = render(items, sources,
                 window_start=datetime.now(timezone.utc) - timedelta(hours=24),
                 window_end=datetime.now(timezone.utc))
    assert "`de`" in out
