from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bxl_eda_worker.models import Item
from bxl_eda_worker.storage import connect, items_in_window, prune_older_than, upsert_items


def _item(url: str, **overrides) -> Item:
    base = dict(
        url=url,
        source="test",
        category="eu_institution",
        title="Test item " + url,
        summary="",
        language="en",
        published_at=datetime.now(timezone.utc),
        fetched_at=datetime.now(timezone.utc),
        topics=["sanctions"],
        regions=[],
        swiss_relevance=False,
    )
    base.update(overrides)
    return Item(**base)


def test_upsert_dedupes_by_url(tmp_path: Path):
    conn = connect(tmp_path / "test.sqlite")
    n1 = upsert_items(conn, [_item("https://example.test/a"), _item("https://example.test/b")])
    n2 = upsert_items(conn, [_item("https://example.test/a"), _item("https://example.test/c")])
    assert n1 == 2
    assert n2 == 1  # 'a' was a dup, only 'c' is new


def test_window_filter_respects_published_at(tmp_path: Path):
    conn = connect(tmp_path / "test.sqlite")
    now = datetime.now(timezone.utc)
    upsert_items(conn, [
        _item("https://example.test/recent", published_at=now - timedelta(hours=1)),
        _item("https://example.test/old",    published_at=now - timedelta(days=5)),
    ])
    in_window = items_in_window(conn, now - timedelta(hours=24), now)
    urls = {it.url for it in in_window}
    assert urls == {"https://example.test/recent"}


def test_prune_removes_old_rows(tmp_path: Path):
    conn = connect(tmp_path / "test.sqlite")
    now = datetime.now(timezone.utc)
    upsert_items(conn, [
        _item("https://example.test/keep",    published_at=now - timedelta(days=10)),
        _item("https://example.test/discard", published_at=now - timedelta(days=200)),
    ])
    pruned = prune_older_than(conn, days=90)
    assert pruned == 1
    remaining = items_in_window(conn, now - timedelta(days=365), now)
    assert {it.url for it in remaining} == {"https://example.test/keep"}


def test_migration_adds_category_to_legacy_db(tmp_path: Path):
    """A v0.1 DB has no category/language columns. connect() should ALTER them in."""
    db = tmp_path / "legacy.sqlite"
    raw = sqlite3.connect(db)
    raw.executescript("""
        CREATE TABLE items (
          id INTEGER PRIMARY KEY,
          url TEXT UNIQUE NOT NULL,
          source TEXT NOT NULL,
          title TEXT NOT NULL,
          summary TEXT NOT NULL DEFAULT '',
          published_at TEXT,
          fetched_at TEXT NOT NULL,
          topics TEXT NOT NULL DEFAULT '[]',
          regions TEXT NOT NULL DEFAULT '[]',
          swiss_relevance INTEGER NOT NULL DEFAULT 0
        );
    """)
    raw.execute("""
        INSERT INTO items (url, source, title, fetched_at)
        VALUES ('https://example.test/legacy', 'old', 'legacy item', ?)
    """, (datetime.now(timezone.utc).isoformat(),))
    raw.commit()
    raw.close()

    # Migration should run on connect, then read should succeed.
    conn = connect(db)
    items = items_in_window(conn, datetime.now(timezone.utc) - timedelta(days=1))
    assert len(items) == 1
    assert items[0].category == "eu_institution"  # default
    assert items[0].language == "en"
