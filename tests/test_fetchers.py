from __future__ import annotations

from datetime import datetime, timezone

import feedparser

from bxl_eda_worker.config import Source
from bxl_eda_worker.fetchers import headless, html, rss

PAGE = """
<html><body>
  <h3><a href="/news/one">EU adopts new sanctions package against Russia</a></h3>
  <h3><a href="/news/one">EU adopts new sanctions package against Russia</a></h3>
  <h3><a href="/news/short">Too short</a></h3>
  <h3><a>No href attribute on this anchor</a></h3>
</body></html>
"""


def _source(**kwargs) -> Source:
    return Source(id="test", name="Test", type="eeas_html", url="https://example.test/", **kwargs)


def test_html_parse_anchors_dedupes_and_filters():
    items = html._parse_anchors(PAGE, "https://example.test/", _source(), "h3 a")
    assert [i.url for i in items] == ["https://example.test/news/one"]
    assert items[0].title == "EU adopts new sanctions package against Russia"


def test_headless_parse_anchors_uses_title_selector():
    page = (
        '<a class="card" href="/press/1"><span class="t">Council extends Iran measures</span>'
        "<time>12:00</time></a>"
    )
    source = _source(title_selector="span.t")
    items = headless._parse_anchors(page, "https://example.test/", source, "a.card")
    assert len(items) == 1
    assert items[0].title == "Council extends Iran measures"


def test_rss_clean_summary_strips_markup():
    assert rss._clean_summary("<p>Foreign <b>Affairs</b>\n Council</p>") == "Foreign Affairs Council"
    assert rss._clean_summary("") == ""


def test_rss_parses_iso_dates_from_atom_updated():
    # Council feed shape: RSS 2.0 with only an Atom <a10:updated> ISO date.
    feed = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<rss xmlns:a10="http://www.w3.org/2005/Atom" version="2.0"><channel>'
        "<title>Council of the EU</title>"
        "<item><link>https://example.test/pr/1</link><title>FAC main results</title>"
        "<a10:updated>2026-10-05T14:50:00Z</a10:updated></item>"
        "</channel></rss>"
    )
    entry = feedparser.parse(feed).entries[0]
    assert rss._parse_date(entry) == datetime(2026, 10, 5, 14, 50, tzinfo=timezone.utc)


def test_rss_parses_rfc2822_dates():
    feed = (
        '<rss version="2.0"><channel><item><link>https://example.test/a</link>'
        "<title>t</title><pubDate>Mon, 05 Oct 2026 16:50:00 +0200</pubDate></item>"
        "</channel></rss>"
    )
    entry = feedparser.parse(feed).entries[0]
    assert rss._parse_date(entry) == datetime(2026, 10, 5, 14, 50, tzinfo=timezone.utc)
