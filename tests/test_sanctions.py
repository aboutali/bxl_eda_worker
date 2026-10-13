from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from bxl_eda_worker.models import Item
from bxl_eda_worker.sanctions import decisions, to_decision, write_sanctions_page

NOW = datetime(2026, 10, 13, 4, 37, tzinfo=timezone.utc)


def _item(title: str, url: str = "https://t/1", source: str = "council_press", **kw) -> Item:
    base = dict(url=url, source=source, category="eu_institution", title=title,
                published_at=NOW, fetched_at=NOW, topics=["sanctions"])
    base.update(kw)
    return Item(**base)


@pytest.mark.parametrize("title, regime, measure, until", [
    ("Myanmar: EU restrictive measures extended until April 2027", "Myanmar", "Renewal", "April 2027"),
    ("Nicaragua: Council extends restrictive measures until 15 October 2027", "Nicaragua", "Renewal", "October 2027"),
    ("Chemical weapons: Council renews framework for restrictive measures and individual listings",
     "Chemical weapons", "Renewal", ""),
    ("Russia’s war of aggression against Ukraine: 20th round of stern EU sanctions hits energy revenues",
     "Russia’s war of aggression against Ukraine", "New package", ""),
    ("Human rights violations in Russia: Council lists ten individuals", "Human rights violations in Russia",
     "New listings", ""),
    ("EU sanctions 10 individuals and 17 entities over unlawful deportation of Ukrainian children",
     "—", "New listings", ""),
    ("Iran: Council delists two entities", "Iran", "Delisting", ""),
])
def test_title_rules(title, regime, measure, until):
    d = to_decision(_item(title))
    assert (d.regime, d.measure, d.valid_until) == (regime, measure, until)


def test_non_decisions_are_skipped():
    assert to_decision(_item("ICC: Statement by the High Representative on behalf of the EU")) is None
    assert to_decision(_item("Russia: EU extends sanctions", source="politico_eu")) is None
    assert to_decision(_item("Foreign Affairs Council, 12 October 2026", topics=["foreign_policy"])) is None


def test_page_lists_newest_first_once(tmp_path: Path):
    older = _item("Myanmar: EU restrictive measures extended until April 2027", "https://a",
                  published_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    newer = _item("Iran: Council lists 5 individuals <IRGC>", "https://b")
    assert [d.url for d in decisions([older, newer, newer])] == ["https://b", "https://a"]
    page = write_sanctions_page([older, newer], NOW, docs_dir=tmp_path).read_text(encoding="utf-8")
    assert "2 decisions" in page
    assert "Iran: Council lists 5 individuals &lt;IRGC&gt;" in page
    assert page.index("https://b") < page.index("https://a")
    assert '<link rel="stylesheet" href="style.css">' in page
