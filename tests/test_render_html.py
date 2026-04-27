from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from bxl_eda_worker.config import Source
from bxl_eda_worker.models import Item
from bxl_eda_worker.render_html import (
    refresh_archive_index,
    render_archive_index,
    render_html,
    write_html_outputs,
)


def _src(id: str, category: str, weight: int = 2, badge: str = "") -> Source:
    return Source(
        id=id, name=f"Source {id}", type="rss", url="https://example.test",
        category=category, weight=weight, badge=badge,
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


def test_html_escapes_title_and_summary():
    sources = [_src("s", "eu_institution")]
    items = [_item("https://t/1", "s", "eu_institution",
                   "<script>alert(1)</script> & friends",
                   summary="A summary with <em>html</em> & ampersands")]
    out = render_html(items, sources,
                     window_start=datetime.now(timezone.utc) - timedelta(hours=24),
                     window_end=datetime.now(timezone.utc))
    # Raw script tags must NOT appear in the output.
    assert "<script>alert" not in out
    # The escaped form should appear.
    assert "&lt;script&gt;alert" in out
    assert "&amp; friends" in out
    assert "<em>html</em>" not in out
    assert "&lt;em&gt;html&lt;/em&gt;" in out


def test_html_writes_index_and_archive(tmp_path: Path):
    sources = [_src("s", "eu_institution")]
    items = [_item("https://t/1", "s", "eu_institution", "Some headline")]
    when = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
    body = render_html(items, sources,
                      window_start=when - timedelta(hours=24), window_end=when)
    index, archive = write_html_outputs(body, date=when, docs_dir=tmp_path)
    assert index.read_text(encoding="utf-8") == body
    assert archive.read_text(encoding="utf-8") == body
    assert archive.name == "2026-04-27.html"


def test_archive_index_lists_files(tmp_path: Path):
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    (archive_dir / "2026-04-27.html").write_text(
        "x 12 items y Swiss-relevance 3 z", encoding="utf-8"
    )
    (archive_dir / "2026-04-26.html").write_text(
        "x 8 items y Swiss-relevance 1 z", encoding="utf-8"
    )
    out = refresh_archive_index(docs_dir=tmp_path)
    text = out.read_text(encoding="utf-8")
    # Most recent first
    idx_27 = text.find("2026-04-27")
    idx_26 = text.find("2026-04-26")
    assert 0 <= idx_27 < idx_26
    assert "12 items" in text
    assert "1 Swiss-relevance" in text


def test_swiss_section_appears_first_in_html():
    sources = [_src("s", "eu_institution")]
    items = [
        _item("https://t/1", "s", "eu_institution", "Sanctions packagex",
              topics=["sanctions"], swiss_relevance=True),
        _item("https://t/2", "s", "eu_institution", "Routine FP statementy",
              topics=["foreign_policy"]),
    ]
    out = render_html(items, sources,
                     window_start=datetime.now(timezone.utc) - timedelta(hours=24),
                     window_end=datetime.now(timezone.utc))
    swiss_idx = out.find("Swiss-relevance highlights")
    eu_idx = out.find("EU institutions")
    assert 0 < swiss_idx < eu_idx
