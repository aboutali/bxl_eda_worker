from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bxl_eda_worker.cluster import cluster_items, is_primary_or_singleton
from bxl_eda_worker.config import Source
from bxl_eda_worker.models import Item


def _src(id: str, category: str, weight: int = 2) -> Source:
    return Source(
        id=id, name=f"Source {id}", type="rss", url="https://example.test",
        category=category, weight=weight,
    )


def _item(url: str, source: str, category: str, title: str, **overrides) -> Item:
    base = dict(
        url=url, source=source, category=category, title=title, language="en",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
        topics=["foreign_policy"], regions=[], swiss_relevance=False,
    )
    base.update(overrides)
    return Item(**base)


def test_singleton_left_unannotated():
    sources = [_src("eeas", "eu_institution")]
    items = [_item("https://t/1", "eeas", "eu_institution",
                   "Iran enrichment levels rising again, IAEA reports",
                   topics=["middle_east"], regions=["iran"])]
    cluster_items(items, sources)
    assert items[0].cluster_role == ""
    assert items[0].cluster_id == ""
    assert items[0].cluster_peers == []


def test_same_story_across_sources_clusters_with_eu_primary():
    sources = [
        _src("eeas",      "eu_institution", weight=3),
        _src("politico",  "press_eu",       weight=2),
        _src("euobserver","press_eu",       weight=2),
    ]
    items = [
        _item(
            "https://eeas/1", "eeas", "eu_institution",
            "EU adopts 14th sanctions package against Russia",
            topics=["sanctions"], regions=["russia"], importance=4,
        ),
        _item(
            "https://politico/1", "politico", "press_eu",
            "EU adopts 14th sanctions package against Russia, targets shadow fleet",
            topics=["sanctions"], regions=["russia"], importance=3,
        ),
        _item(
            "https://euobserver/1", "euobserver", "press_eu",
            "Russia: EU adopts 14th sanctions package",
            topics=["sanctions"], regions=["russia"], importance=3,
        ),
    ]
    cluster_items(items, sources)
    primary = next(it for it in items if it.cluster_role == "primary")
    secondaries = [it for it in items if it.cluster_role == "secondary"]
    assert primary.source == "eeas", "EU institution should win primary slot"
    assert len(secondaries) == 2
    assert {p["source"] for p in primary.cluster_peers} == {"politico", "euobserver"}
    # Secondaries share the same cluster_id and have empty peer lists.
    assert all(s.cluster_id == primary.cluster_id for s in secondaries)
    assert all(s.cluster_peers == [] for s in secondaries)


def test_distinct_stories_same_topic_dont_cluster():
    sources = [
        _src("eeas",     "eu_institution", weight=3),
        _src("politico", "press_eu",       weight=2),
    ]
    items = [
        _item(
            "https://eeas/1", "eeas", "eu_institution",
            "EU sanctions Iran-aligned shipping firm over Red Sea attacks",
            topics=["sanctions"], regions=["iran"],
            summary_oneliner="EU lists three Iran-aligned shippers over Red Sea drone attacks.",
        ),
        _item(
            "https://politico/1", "politico", "press_eu",
            "Iran: nuclear talks resume in Vienna with new IAEA proposal",
            topics=["foreign_policy"], regions=["iran"],
            summary_oneliner="Iran returns to Vienna for IAEA-brokered nuclear track.",
        ),
    ]
    cluster_items(items, sources)
    assert all(it.cluster_role == "" for it in items), \
        "Distinct Iran stories with no title overlap must remain separate"


def test_same_source_items_never_cluster():
    sources = [_src("politico", "press_eu", weight=2)]
    items = [
        _item("https://politico/1", "politico", "press_eu",
              "EU adopts 14th sanctions package against Russia",
              topics=["sanctions"], regions=["russia"]),
        _item("https://politico/2", "politico", "press_eu",
              "EU adopts 14th sanctions package against Russia explainer",
              topics=["sanctions"], regions=["russia"]),
    ]
    cluster_items(items, sources)
    # Even though titles overlap heavily, same-source items are kept distinct.
    assert all(it.cluster_role == "" for it in items)


def test_oneliner_signal_with_region_overlap_clusters():
    sources = [
        _src("council",  "eu_institution", weight=3),
        _src("reuters",  "press_intl",     weight=2),
    ]
    # Titles diverge stylistically but the LLM oneliner converges on the same
    # story; with shared region, this should cluster.
    items = [
        _item(
            "https://council/1", "council", "eu_institution",
            "Foreign Affairs Council conclusions on Lebanon situation adopted",
            topics=["foreign_policy"], regions=["lebanon"],
            summary_oneliner="EU foreign ministers adopt conclusions calling for Lebanon de-escalation and renewed UNIFIL mandate.",
        ),
        _item(
            "https://reuters/1", "reuters", "press_intl",
            "EU ministers urge restraint as Lebanon tensions persist",
            topics=["foreign_policy"], regions=["lebanon"],
            summary_oneliner="EU foreign ministers adopt conclusions calling for Lebanon de-escalation and UNIFIL renewal.",
        ),
    ]
    cluster_items(items, sources)
    primary = [it for it in items if it.cluster_role == "primary"]
    assert len(primary) == 1
    assert primary[0].source == "council"


def test_is_primary_or_singleton_excludes_only_secondaries():
    sources = [
        _src("eeas",     "eu_institution", weight=3),
        _src("politico", "press_eu",       weight=2),
    ]
    items = [
        _item("https://eeas/1", "eeas", "eu_institution",
              "EU adopts 14th sanctions package against Russia",
              topics=["sanctions"], regions=["russia"]),
        _item("https://politico/1", "politico", "press_eu",
              "EU adopts 14th sanctions package against Russia, targets shadow fleet",
              topics=["sanctions"], regions=["russia"]),
        _item("https://eeas/2", "eeas", "eu_institution",
              "Standalone story unrelated to anything above",
              topics=["foreign_policy"]),
    ]
    cluster_items(items, sources)
    visible = [it for it in items if is_primary_or_singleton(it)]
    assert len(visible) == 2  # one primary + one singleton; secondary dropped
