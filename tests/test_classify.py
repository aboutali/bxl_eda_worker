from __future__ import annotations

from datetime import datetime, timezone

from bxl_eda_worker.classify import classify, is_relevant
from bxl_eda_worker.models import Item


def _item(title: str, summary: str = "") -> Item:
    return Item(
        url=f"https://example.test/{abs(hash(title))}",
        source="test",
        title=title,
        summary=summary,
        fetched_at=datetime.now(timezone.utc),
    )


def test_romanian_does_not_match_oman():
    """Regression: substring match used to tag 'Romanian' with region 'oman'."""
    it = classify(_item("Romanian socialists and far right unveil joint plan to topple PM"))
    assert "oman" not in it.regions
    # No middle-east hit at all from this title.
    assert "middle_east" not in it.topics


def test_iran_in_iranian_matches():
    it = classify(_item("Iranian foreign minister meets EU envoy"))
    assert "middle_east" in it.topics
    assert "iranian" in it.regions  # 'iran' would also match but we list both


def test_sanctions_keyword_flags_swiss_relevance():
    it = classify(_item("Council adopts 17th sanctions package against Russia"))
    assert "sanctions" in it.topics
    assert it.swiss_relevance is True  # SECO-alignment trigger


def test_explicit_swiss_keyword_flags_relevance_without_sanctions():
    it = classify(_item("Switzerland mulls position on EU foreign-policy initiative"))
    assert it.swiss_relevance is True


def test_unrelated_item_not_relevant():
    it = classify(_item("Commission approves €72m Hungarian state aid for tyre plant"))
    assert is_relevant(it) is False


def test_hrvp_kallas_flags_foreign_policy():
    it = classify(_item("HR/VP Kallas travels to Brunei Darussalam"))
    assert "foreign_policy" in it.topics


def test_fac_word_boundary():
    """`fac` must not match `facade`, `facility`, `facebook`."""
    it = classify(_item("New facility opens in Brussels for facade restoration"))
    assert "foreign_policy" not in it.topics
