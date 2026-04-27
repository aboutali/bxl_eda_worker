from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bxl_eda_worker.models import Item

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id            INTEGER PRIMARY KEY,
  url           TEXT UNIQUE NOT NULL,
  source        TEXT NOT NULL,
  title         TEXT NOT NULL,
  summary       TEXT NOT NULL DEFAULT '',
  published_at  TEXT,
  fetched_at    TEXT NOT NULL,
  topics        TEXT NOT NULL DEFAULT '[]',
  regions       TEXT NOT NULL DEFAULT '[]',
  swiss_relevance INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at);
CREATE INDEX IF NOT EXISTS idx_items_source    ON items(source);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_items(conn: sqlite3.Connection, items: list[Item]) -> int:
    """Insert items, ignoring duplicates by URL. Returns count of new rows."""
    if not items:
        return 0
    rows = [
        (
            it.url,
            it.source,
            it.title,
            it.summary,
            it.published_at.isoformat() if it.published_at else None,
            it.fetched_at.isoformat(),
            json.dumps(it.topics),
            json.dumps(it.regions),
            1 if it.swiss_relevance else 0,
        )
        for it in items
    ]
    cur = conn.executemany(
        """
        INSERT OR IGNORE INTO items
          (url, source, title, summary, published_at, fetched_at,
           topics, regions, swiss_relevance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    return cur.rowcount


def items_in_window(
    conn: sqlite3.Connection,
    since: datetime,
    until: datetime | None = None,
) -> list[Item]:
    until = until or datetime.now(timezone.utc)
    cur = conn.execute(
        """
        SELECT url, source, title, summary, published_at, fetched_at,
               topics, regions, swiss_relevance
        FROM items
        WHERE COALESCE(published_at, fetched_at) >= ?
          AND COALESCE(published_at, fetched_at) <  ?
        ORDER BY COALESCE(published_at, fetched_at) DESC
        """,
        (since.isoformat(), until.isoformat()),
    )
    return [_row_to_item(row) for row in cur.fetchall()]


def prune_older_than(conn: sqlite3.Connection, days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cur = conn.execute(
        "DELETE FROM items WHERE COALESCE(published_at, fetched_at) < ?",
        (cutoff.isoformat(),),
    )
    conn.commit()
    return cur.rowcount


def _row_to_item(row: sqlite3.Row) -> Item:
    return Item(
        url=row["url"],
        source=row["source"],
        title=row["title"],
        summary=row["summary"] or "",
        published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        topics=json.loads(row["topics"]),
        regions=json.loads(row["regions"]),
        swiss_relevance=bool(row["swiss_relevance"]),
    )
