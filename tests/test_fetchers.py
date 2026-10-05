from __future__ import annotations

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
