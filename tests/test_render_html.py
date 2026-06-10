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


def test_archive_index_handles_weekly_entries(tmp_path: Path):
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    (archive_dir / "2026-W17.html").write_text(
        "x 23 items y Swiss-relevance 4 z", encoding="utf-8"
    )
    (archive_dir / "2026-04-27.html").write_text(
        "x 12 items y Swiss-relevance 3 z", encoding="utf-8"
    )
    (archive_dir / "2026-W01.html").write_text(
        "x 18 items y Swiss-relevance 2 z", encoding="utf-8"
    )
    out = refresh_archive_index(docs_dir=tmp_path)
    text = out.read_text(encoding="utf-8")
    # Daily 04-27 is more recent than the Monday of W17 (Apr 20) — should come first.
    idx_daily = text.find("2026-04-27")
    idx_w17 = text.find("2026-W17")
    idx_w01 = text.find("2026-W01")
    assert 0 <= idx_daily < idx_w17 < idx_w01
    assert "weekly" in text  # the kind tag
    assert "Apr 20" in text or "Apr 26" in text  # human range label on weeklies


def test_archive_index_ignores_non_digest_files(tmp_path: Path):
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    (archive_dir / "2026-04-27.html").write_text("x 1 items y Swiss-relevance 0 z", encoding="utf-8")
    (archive_dir / "random.html").write_text("ignore me", encoding="utf-8")
    out = refresh_archive_index(docs_dir=tmp_path)
    text = out.read_text(encoding="utf-8")
    assert "random.html" not in text


def _win():
    now = datetime.now(timezone.utc)
    return dict(window_start=now - timedelta(hours=24), window_end=now)


def test_html_no_swiss_section_swiss_item_marked_inline():
    sources = [_src("s", "eu_institution")]
    items = [
        _item("https://t/1", "s", "eu_institution", "Sanctions packagex",
              topics=["sanctions"], swiss_relevance=True),
    ]
    out = render_html(items, sources, **_win())
    assert "swiss-highlights" not in out          # dedicated section removed
    assert "Swiss-relevance highlights" not in out
    assert "tag-seco" in out                       # marked inline instead


def test_html_multi_topic_item_appears_exactly_once():
    sources = [_src("s", "eu_institution")]
    items = [_item("https://t/dup", "s", "eu_institution",
                   "Russia sanctions hit Mideast trade",
                   topics=["sanctions", "middle_east"])]
    out = render_html(items, sources, **_win())
    assert out.count("https://t/dup") == 1


def test_html_multi_topic_item_shows_topic_chips():
    sources = [_src("s", "eu_institution")]
    items = [_item("https://t/dup", "s", "eu_institution",
                   "Russia sanctions hit Mideast trade",
                   topics=["sanctions", "middle_east"])]
    out = render_html(items, sources, **_win())
    assert '<span class="topic">Sanctions</span>' in out
    assert '<span class="topic">Middle East</span>' in out


def test_html_topic_subheaders_gone_but_category_remains():
    sources = [_src("s", "eu_institution")]
    items = [
        _item("https://t/1", "s", "eu_institution", "A", topics=["sanctions"]),
        _item("https://t/2", "s", "eu_institution", "B", topics=["middle_east"]),
    ]
    out = render_html(items, sources, **_win())
    assert "<h3>Sanctions</h3>" not in out
    assert "<h3>Middle East</h3>" not in out
    assert "<h2>🇪🇺 EU institutions</h2>" in out  # category header stays


def test_html_swiss_item_without_rationale_still_marked():
    sources = [_src("s", "eu_institution")]
    items = [_item("https://t/1", "s", "eu_institution", "Bern watches FP shift",
                   topics=["foreign_policy"], swiss_relevance=True)]
    out = render_html(items, sources, **_win())
    assert "🇨🇭 Swiss-relevant" in out


def test_html_multilateral_forum_statements_go_to_brief_aside():
    sources = [_src("eeas_press", "eu_institution")]
    items = [
        _item("https://e/normal", "eeas_press", "eu_institution",
              "HR/VP Kallas statement on Ukraine", topics=["foreign_policy"]),
        _item("https://e/osce", "eeas_press", "eu_institution",
              "OSCE Permanent Council - EU Statement on Ukraine", topics=["foreign_policy"],
              summary_oneliner="Routine OSCE statement."),
    ]
    out = render_html(items, sources, **_win())
    assert "forum-aside" in out  # the brief aside section
    aside_idx = out.index("forum-aside")
    assert out.index("https://e/osce") > aside_idx
    assert out.index("https://e/normal") < aside_idx
    assert "Routine OSCE statement." not in out  # content-less aside


def test_html_footer_has_made_with_tagline():
    sources = [_src("s", "eu_institution")]
    items = [_item("https://t/1", "s", "eu_institution", "X")]
    out = render_html(items, sources, **_win())
    assert "Made with &lt;3 for SER" in out  # < is escaped in HTML
