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


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now())
    swiss_idx = out.find("🇨🇭 Swiss confederation")
    eu_idx = out.find("🇪🇺 EU institutions")
    assert 0 < swiss_idx < eu_idx, "Swiss section must precede EU section"


def test_headline_renders_at_top_when_provided():
    sources = [_src("eeas", "eu_institution")]
    items = [_item("https://t/1", "eeas", "eu_institution", "X", topics=["foreign_policy"])]
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now(),
                 headline="Ministers met. They talked. They left.")
    assert "## Today" in out
    assert "Ministers met." in out
    today_idx = out.find("## Today")
    eu_idx = out.find("🇪🇺 EU institutions")
    assert 0 < today_idx < eu_idx


def test_headline_section_omitted_when_empty():
    sources = [_src("eeas", "eu_institution")]
    items = [_item("https://t/1", "eeas", "eu_institution", "X", topics=["foreign_policy"])]
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now())
    assert "## Today" not in out


def test_swiss_relevance_highlights_appear_first():
    sources = [_src("eeas", "eu_institution")]
    items = [
        _item("https://t/1", "eeas", "eu_institution", "Sanctions package",
              topics=["sanctions"], swiss_relevance=True),
    ]
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now())
    highlights_idx = out.find("Swiss-relevance highlights")
    eu_section_idx = out.find("🇪🇺 EU institutions")
    assert 0 < highlights_idx < eu_section_idx


def test_badge_renders_next_to_source_name():
    sources = [_src("council", "eu_institution", badge="FAC")]
    items = [_item("https://t/1", "council", "eu_institution",
                   "Foreign Affairs Council adopts conclusions",
                   topics=["foreign_policy"])]
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now())
    assert "Source council FAC" in out


def test_non_english_language_marker():
    sources = [_src("nzz", "press_swiss")]
    items = [_item("https://t/1", "nzz", "press_swiss",
                   "EU verhängt neue Sanktionen", language="de",
                   topics=["sanctions"], swiss_relevance=True)]
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now())
    assert "`de`" in out


def test_oneliner_replaces_raw_summary_when_present():
    sources = [_src("eeas", "eu_institution")]
    items = [_item("https://t/1", "eeas", "eu_institution", "Something happened",
                   summary="Long raw RSS blurb that we want to suppress",
                   summary_oneliner="Tight one-liner from the LLM.",
                   topics=["foreign_policy"])]
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now())
    assert "Tight one-liner" in out
    assert "Long raw RSS blurb" not in out


def test_importance_stars_render_for_high_items_only():
    sources = [_src("eeas", "eu_institution")]
    items = [
        _item("https://t/1", "eeas", "eu_institution", "Routine boilerplate",
              importance=2, topics=["foreign_policy"]),
        _item("https://t/2", "eeas", "eu_institution", "Major story",
              importance=5, topics=["foreign_policy"]),
    ]
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now())
    assert "★5" in out
    assert "★2" not in out  # importance < 4 → no star marker
