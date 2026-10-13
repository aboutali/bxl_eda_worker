"""Real weekly synthesis pages, built from the stored items of a finished week.

The daily run calls `write_weekly` after the daily page. It writes
docs/archive/YYYY-WNN.html for the last completed ISO week once, and replaces
a simulated `seed-archive` page of the same week (marked by SIMULATED_MARKER).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from bxl_eda_worker.analyze import compose_headline
from bxl_eda_worker.classify import is_multilateral_forum_statement
from bxl_eda_worker.cluster import cluster_items, is_primary_or_singleton
from bxl_eda_worker.config import Source
from bxl_eda_worker.render_html import DOCS_DIR, _rebase_for_archive, render_html
from bxl_eda_worker.storage import items_in_window

log = logging.getLogger(__name__)

SIMULATED_MARKER = '<aside class="simulated">'


def last_completed_week(today: date) -> tuple[str, date, date]:
    """(label, monday, sunday) of the ISO week before the one containing `today`."""
    monday = today - timedelta(days=today.weekday() + 7)
    sunday = monday + timedelta(days=6)
    iso = monday.isocalendar()
    return f"{iso.year}-W{iso.week:02d}", monday, sunday


def is_simulated(path: Path) -> bool:
    return SIMULATED_MARKER in path.read_text(encoding="utf-8")


def write_weekly(
    conn: sqlite3.Connection,
    sources: list[Source],
    today: date,
    *,
    docs_dir: Path = DOCS_DIR,
) -> Path | None:
    label, monday, sunday = last_completed_week(today)
    target = docs_dir / "archive" / f"{label}.html"
    if target.exists() and not is_simulated(target):
        return None

    start = datetime.combine(monday, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=7)
    items = items_in_window(conn, start, end)
    if not items:
        log.info("weekly %s: no stored items, skipping", label)
        return None

    cluster_items(items, sources)
    primaries = [
        it for it in items
        if is_primary_or_singleton(it) and not is_multilateral_forum_statement(it)
    ]
    headline = compose_headline(
        primaries, weekly=True,
        period_label=f"the week {label} ({monday:%d %b} – {sunday:%d %b %Y})",
    )
    body = render_html(items, sources, window_start=start, window_end=end, headline=headline)
    body = body.replace(
        f"<title>EU FP Digest — {end:%Y-%m-%d}</title>",
        f"<title>EU FP Weekly — {label}</title>", 1,
    )
    body = body.replace("<h2>Today</h2>", "<h2>This week</h2>", 1)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_rebase_for_archive(body), encoding="utf-8")
    log.info("weekly %s: wrote %s (%d items)", label, target, len(items))
    return target
