from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from bxl_eda_worker import weekly
from bxl_eda_worker.config import Source
from bxl_eda_worker.events import extract_events, parse_event_title
from bxl_eda_worker.models import Item
from bxl_eda_worker.render_html import refresh_archive_index, render_html, write_html_outputs
from bxl_eda_worker.storage import connect, upcoming_events, upsert_events, upsert_items

NOW = datetime(2026, 10, 13, 4, 37, tzinfo=timezone.utc)


def _src() -> Source:
    return Source(id="council_press", name="Council", type="rss", url="https://x", category="eu_institution")


def _item(title: str, url: str = "https://t/1", **kw) -> Item:
    base = dict(url=url, source="council_press", category="eu_institution", title=title,
                published_at=NOW, fetched_at=NOW, topics=["sanctions"])
    base.update(kw)
    return Item(**base)


def test_parse_event_titles():
    ev = parse_event_title("Media advisory - Foreign Affairs Council of 12 October 2026", "u")
    assert (ev.when, ev.name) == (date(2026, 10, 12), "Foreign Affairs Council")
    ev = parse_event_title("Press briefing – Economic and Financial Affairs Council of 9 October 2026", "u")
    assert (ev.when, ev.name) == (date(2026, 10, 9), "Economic and Financial Affairs Council")
    ev = parse_event_title("Media advisory - European Council of 23-24 October 2026", "u")
    assert (ev.when, ev.name) == (date(2026, 10, 23), "European Council")
    assert parse_event_title("Forward look: 12 - 25 October 2026", "u") is None
    assert parse_event_title("Media advisory – press conference on the MFF", "u") is None


def test_extract_events_merges_advisory_and_briefing():
    items = [
        _item("Media advisory - Foreign Affairs Council of 20 October 2026", "https://a"),
        _item("Press briefing - Foreign Affairs Council of 20 October 2026", "https://b"),
        _item("Media advisory - Foreign Affairs Council of 20 October 2026", "https://c", source="politico_eu"),
    ]
    events = extract_events(items)
    assert [(e.name, e.url) for e in events] == [("Foreign Affairs Council", "https://a")]


def test_upcoming_events_and_coming_up_box(tmp_path: Path):
    conn = connect(tmp_path / "db.sqlite")
    upsert_events(conn, extract_events([
        _item("Media advisory - Foreign Affairs Council of 20 October 2026", "https://a"),
        _item("Media advisory - General Affairs Council of 10 October 2026", "https://b"),
    ]))
    coming = upcoming_events(conn, date(2026, 10, 13))
    assert [e.name for e in coming] == ["Foreign Affairs Council"]
    out = render_html([], [_src()], window_start=NOW - timedelta(hours=24), window_end=NOW, events=coming)
    assert '<time datetime="2026-10-20">Tue 20 Oct</time> <a href="https://a">Foreign Affairs Council</a>' in out


def test_last_completed_week():
    assert weekly.last_completed_week(date(2026, 10, 13)) == ("2026-W41", date(2026, 10, 5), date(2026, 10, 11))
    assert weekly.last_completed_week(date(2026, 10, 18)) == ("2026-W41", date(2026, 10, 5), date(2026, 10, 11))


def test_write_weekly_replaces_simulated_but_not_real(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(weekly, "compose_headline", lambda items, **kw: "Week lede.")
    conn = connect(tmp_path / "db.sqlite")
    upsert_items(conn, [_item("EU sanctions Russia listings", published_at=datetime(2026, 10, 7, 9, tzinfo=timezone.utc))])
    archive = tmp_path / "archive"
    archive.mkdir()
    target = archive / "2026-W41.html"
    target.write_text('<main><aside class="simulated">fake</aside></main>', encoding="utf-8")

    out = weekly.write_weekly(conn, [_src()], date(2026, 10, 13), docs_dir=tmp_path)
    page = target.read_text(encoding="utf-8")
    assert out == target
    assert "<title>EU FP Weekly — 2026-W41</title>" in page
    assert "<h2>This week</h2>" in page and "Week lede." in page
    assert "EU sanctions Russia listings" in page
    assert 'href="../style.css"' in page and "simulated" not in page

    target.write_text("real page", encoding="utf-8")
    assert weekly.write_weekly(conn, [_src()], date(2026, 10, 13), docs_dir=tmp_path) is None
    assert target.read_text(encoding="utf-8") == "real page"


def test_search_index_lists_daily_items_only(tmp_path: Path):
    body = render_html(
        [_item("Council lists 10 individuals &amp; entities", summary_oneliner="EU adds listings over Zürich-based firms.")],
        [_src()], window_start=NOW - timedelta(hours=24), window_end=NOW,
    )
    write_html_outputs(body, date=NOW, docs_dir=tmp_path)
    (tmp_path / "archive" / "2026-W41.html").write_text(body, encoding="utf-8")
    out = refresh_archive_index(docs_dir=tmp_path)
    rows = json.loads((tmp_path / "archive" / "search-index.json").read_text(encoding="utf-8"))
    assert rows == [["2026-10-13", "Council lists 10 individuals &amp; entities", "https://t/1",
                     "EU adds listings over Zürich-based firms."]]
    assert 'id="q"' in out.read_text(encoding="utf-8")
