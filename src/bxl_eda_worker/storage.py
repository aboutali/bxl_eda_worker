from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bxl_eda_worker.models import Item

TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id               INTEGER PRIMARY KEY,
  url              TEXT UNIQUE NOT NULL,
  source           TEXT NOT NULL,
  category         TEXT NOT NULL DEFAULT 'eu_institution',
  title            TEXT NOT NULL,
  summary          TEXT NOT NULL DEFAULT '',
  language         TEXT NOT NULL DEFAULT 'en',
  published_at     TEXT,
  fetched_at       TEXT NOT NULL,
  topics           TEXT NOT NULL DEFAULT '[]',
  regions          TEXT NOT NULL DEFAULT '[]',
  swiss_relevance  INTEGER NOT NULL DEFAULT 0,
  summary_oneliner TEXT NOT NULL DEFAULT '',
  swiss_rationale  TEXT NOT NULL DEFAULT '',
  importance       INTEGER NOT NULL DEFAULT 0
);
"""

INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at);
CREATE INDEX IF NOT EXISTS idx_items_source    ON items(source);
CREATE INDEX IF NOT EXISTS idx_items_category  ON items(category);
"""

# Columns added after first release. Each entry: (column_name, ALTER fragment).
_MIGRATIONS = [
    ("category",         "ALTER TABLE items ADD COLUMN category TEXT NOT NULL DEFAULT 'eu_institution'"),
    ("language",         "ALTER TABLE items ADD COLUMN language TEXT NOT NULL DEFAULT 'en'"),
    ("summary_oneliner", "ALTER TABLE items ADD COLUMN summary_oneliner TEXT NOT NULL DEFAULT ''"),
    ("swiss_rationale",  "ALTER TABLE items ADD COLUMN swiss_rationale TEXT NOT NULL DEFAULT ''"),
    ("importance",       "ALTER TABLE items ADD COLUMN importance INTEGER NOT NULL DEFAULT 0"),
]


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(TABLE_SCHEMA)
    _migrate(conn)
    conn.executescript(INDEX_SCHEMA)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(items)")
    existing = {row["name"] for row in cur.fetchall()}
    for col, alter_sql in _MIGRATIONS:
        if col not in existing:
            conn.execute(alter_sql)
    conn.commit()


def upsert_items(conn: sqlite3.Connection, items: list[Item]) -> int:
    if not items:
        return 0
    rows = [
        (
            it.url, it.source, it.category, it.title, it.summary, it.language,
            it.published_at.isoformat() if it.published_at else None,
            it.fetched_at.isoformat(),
            json.dumps(it.topics), json.dumps(it.regions),
            1 if it.swiss_relevance else 0,
            it.summary_oneliner, it.swiss_rationale, it.importance,
        )
        for it in items
    ]
    cur = conn.executemany(
        """
        INSERT INTO items
          (url, source, category, title, summary, language,
           published_at, fetched_at, topics, regions, swiss_relevance,
           summary_oneliner, swiss_rationale, importance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
          summary_oneliner = excluded.summary_oneliner,
          swiss_rationale  = excluded.swiss_rationale,
          importance       = excluded.importance,
          topics           = excluded.topics,
          regions          = excluded.regions,
          swiss_relevance  = excluded.swiss_relevance
        WHERE excluded.summary_oneliner != '' AND items.summary_oneliner = ''
        """,
        rows,
    )
    conn.commit()
    # `rowcount` includes both inserts and conditional updates; close enough
    # for the log line — the alternative is two queries.
    return cur.rowcount


def items_in_window(
    conn: sqlite3.Connection,
    since: datetime,
    until: datetime | None = None,
) -> list[Item]:
    until = until or datetime.now(timezone.utc)
    cur = conn.execute(
        """
        SELECT url, source, category, title, summary, language,
               published_at, fetched_at, topics, regions, swiss_relevance,
               summary_oneliner, swiss_rationale, importance
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
        category=row["category"],
        title=row["title"],
        summary=row["summary"] or "",
        language=row["language"],
        published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        topics=json.loads(row["topics"]),
        regions=json.loads(row["regions"]),
        swiss_relevance=bool(row["swiss_relevance"]),
        summary_oneliner=row["summary_oneliner"] or "",
        swiss_rationale=row["swiss_rationale"] or "",
        importance=row["importance"] or 0,
    )
