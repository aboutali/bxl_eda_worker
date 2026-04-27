from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from bxl_eda_worker.config import DATA_DIR

# Bump when the system prompt changes; invalidates all cached enrichments.
PROMPT_VERSION = 1

_DB_PATH = DATA_DIR / "llm_cache.sqlite"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS enrichments (
  url            TEXT NOT NULL,
  prompt_version INTEGER NOT NULL,
  model          TEXT NOT NULL,
  payload_json   TEXT NOT NULL,
  cached_at      TEXT NOT NULL,
  PRIMARY KEY (url, prompt_version, model)
);
"""


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def get(url: str, model: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT payload_json FROM enrichments WHERE url=? AND prompt_version=? AND model=?",
            (url, PROMPT_VERSION, model),
        ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def put(url: str, model: str, payload: dict) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO enrichments
              (url, prompt_version, model, payload_json, cached_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                url, PROMPT_VERSION, model,
                json.dumps(payload),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
