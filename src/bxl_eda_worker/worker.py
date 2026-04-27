from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from bxl_eda_worker.classify import classify, is_relevant
from bxl_eda_worker.config import DB_PATH, ensure_dirs, load_sources
from bxl_eda_worker.digest import render, write_digest
from bxl_eda_worker.fetchers import (
    HeadlessUnavailable,
    browser_context,
    fetch_eeas_html,
    fetch_headless_html,
    fetch_rss,
)
from bxl_eda_worker.fetchers.rss import TIMEOUT, USER_AGENT
from bxl_eda_worker.storage import (
    connect,
    items_in_window,
    prune_older_than,
    upsert_items,
)

log = logging.getLogger(__name__)
RETENTION_DAYS = 90


def run(window_hours: int = 24, *, skip_headless: bool = False) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    ensure_dirs()
    sources = load_sources()
    log.info("loaded %d sources", len(sources))

    rss_sources = [s for s in sources if s.type == "rss"]
    eeas_sources = [s for s in sources if s.type == "eeas_html"]
    headless_sources = [s for s in sources if s.type == "headless_html"]
    other = [
        s for s in sources
        if s.type not in {"rss", "eeas_html", "headless_html"}
    ]
    for s in other:
        log.warning("source %s has unsupported type %r, skipping", s.id, s.type)

    fresh: list = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT) as client:
        for src in rss_sources:
            items = fetch_rss(src, client=client)
            log.info("[rss] %s: fetched %d items", src.id, len(items))
            fresh.extend(items)
        for src in eeas_sources:
            items = fetch_eeas_html(src, client=client)
            log.info("[html] %s: fetched %d items", src.id, len(items))
            fresh.extend(items)

    if headless_sources and not skip_headless:
        try:
            with browser_context() as ctx:
                for src in headless_sources:
                    items = fetch_headless_html(src, context=ctx)
                    log.info("[headless] %s: fetched %d items", src.id, len(items))
                    fresh.extend(items)
        except HeadlessUnavailable as exc:
            log.warning(
                "skipping %d headless sources — %s",
                len(headless_sources), exc,
            )
    elif skip_headless:
        log.info("skipping %d headless sources (--skip-headless)", len(headless_sources))

    classified = [classify(it) for it in fresh]
    relevant = [it for it in classified if is_relevant(it)]
    log.info("classified %d items, %d relevant", len(classified), len(relevant))

    conn = connect(DB_PATH)
    try:
        new_count = upsert_items(conn, relevant)
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
