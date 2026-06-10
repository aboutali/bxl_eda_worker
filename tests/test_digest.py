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


def test_no_swiss_highlights_section_swiss_item_marked_inline():
    sources = [_src("eeas", "eu_institution")]
    items = [
        _item("https://t/1", "eeas", "eu_institution", "Sanctions package",
              topics=["sanctions"], swiss_relevance=True),
    ]
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now())
    assert "Swiss-relevance highlights" not in out  # dedicated section removed
    assert "🇨🇭 SECO alignment likely" in out         # marked inline instead


def test_multi_topic_item_appears_exactly_once():
    sources = [_src("eeas", "eu_institution")]
    items = [
        _item("https://t/dup", "eeas", "eu_institution",
              "Russia sanctions hit Mideast trade",
              topics=["sanctions", "middle_east"]),
    ]
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now())
    assert out.count("https://t/dup") == 1


def test_multi_topic_item_shows_all_topics_as_tags():
    sources = [_src("eeas", "eu_institution")]
    items = [
        _item("https://t/dup", "eeas", "eu_institution",
              "Russia sanctions hit Mideast trade",
              topics=["sanctions", "middle_east"]),
    ]
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now())
    assert "🏷 Sanctions · Middle East" in out


def test_topic_subsection_headers_are_gone_but_category_remains():
    sources = [_src("eeas", "eu_institution")]
    items = [
        _item("https://t/1", "eeas", "eu_institution", "A", topics=["sanctions"]),
        _item("https://t/2", "eeas", "eu_institution", "B", topics=["middle_east"]),
    ]
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now())
    assert "### Sanctions" not in out
    assert "### Middle East" not in out
    assert "## 🇪🇺 EU institutions" in out  # category header stays


def test_swiss_relevant_item_without_rationale_still_marked():
    sources = [_src("eeas", "eu_institution")]
    items = [
        _item("https://t/1", "eeas", "eu_institution", "Bern watches FP shift",
              topics=["foreign_policy"], swiss_relevance=True),
    ]
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now())
    assert "🇨🇭 Swiss-relevant" in out


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


def test_multilateral_forum_statements_go_to_brief_aside():
    sources = [_src("eeas_press", "eu_institution")]
    items = [
        _item("https://e/normal", "eeas_press", "eu_institution",
              "HR/VP Kallas statement on Ukraine", topics=["foreign_policy"],
              summary_oneliner="A normal EEAS foreign-policy item."),
        _item("https://e/iaea", "eeas_press", "eu_institution",
              "EU Statement - Board of Governors International Atomic Energy Agency (IAEA)",
              topics=["middle_east"], summary_oneliner="Routine IAEA statement text."),
    ]
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now())
    assert "Multilateral-forum statements" in out
    aside_idx = out.index("Multilateral-forum statements")
    # Forum item lives in the aside (after the heading); the normal item in main (before).
    assert out.index("https://e/iaea") > aside_idx
    assert out.index("https://e/normal") < aside_idx
    # The aside is content-less: the forum item's one-liner is NOT rendered.
    assert "Routine IAEA statement text." not in out
    # The normal item keeps its one-liner in the main body.
    assert "A normal EEAS foreign-policy item." in out


def test_footer_has_made_with_tagline():
    sources = [_src("eeas", "eu_institution")]
    items = [_item("https://t/1", "eeas", "eu_institution", "X", topics=["foreign_policy"])]
    out = render(items, sources, window_start=_now() - timedelta(hours=24), window_end=_now())
    assert "Made with <3 for SER" in out
