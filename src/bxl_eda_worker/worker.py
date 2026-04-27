from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from bxl_eda_worker.classify import classify, is_relevant
from bxl_eda_worker.config import DB_PATH, ensure_dirs, load_sources
from bxl_eda_worker.digest import render, write_digest
from bxl_eda_worker.fetchers import fetch_eeas_html, fetch_rss
from bxl_eda_worker.fetchers.rss import TIMEOUT, USER_AGENT

FETCHERS = {
    "rss": fetch_rss,
    "eeas_html": fetch_eeas_html,
}
from bxl_eda_worker.storage import (
    connect,
    items_in_window,
    prune_older_than,
    upsert_items,
)

log = logging.getLogger(__name__)
RETENTION_DAYS = 90


def run(window_hours: int = 24) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    ensure_dirs()
    sources = load_sources()
    log.info("loaded %d sources", len(sources))

    fresh: list = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT) as client:
        for src in sources:
            fetcher = FETCHERS.get(src.type)
            if fetcher is None:
                log.warning("source %s has unsupported type %r, skipping", src.id, src.type)
                continue
            items = fetcher(src, client=client)
            log.info("%s: fetched %d items", src.id, len(items))
            for it in items:
                classify(it)
            fresh.extend(it for it in items if is_relevant(it))

    conn = connect(DB_PATH)
    try:
        new_count = upsert_items(conn, fresh)
        pruned = prune_older_than(conn, RETENTION_DAYS)
        log.info("stored %d new items (pruned %d older than %d days)", new_count, pruned, RETENTION_DAYS)

        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=window_hours)
        digest_items = items_in_window(conn, window_start, now)
        digest = render(digest_items, sources, window_start=window_start, window_end=now)
        path = write_digest(digest, date=now)
        log.info("wrote digest %s (%d items)", path, len(digest_items))
    finally:
        conn.close()
