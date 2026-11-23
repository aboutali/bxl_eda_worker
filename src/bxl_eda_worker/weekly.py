"""Real weekly synthesis pages, built from the stored items of a finished week.

The daily run calls `write_weekly` after the daily page. It writes
docs/archive/YYYY-WNN.html for the last completed ISO week once, and replaces
a simulated `seed-archive` page of the same week (marked by SIMULATED_MARKER).

It also looks back REPAIR_WEEKS weeks for real pages written without a lede
(the LLM was down, e.g. an empty credit balance) and rewrites each one once a
lede can be composed. Those weeks' items were never enriched, so the weekly
lede is written from their titles.
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
LEDE_MARKER = '<p class="lede">'
# Weeks to look back for lede-less pages; items are kept for 90 days.
REPAIR_WEEKS = 8


def last_completed_week(today: date) -> tuple[str, date, date]:
    """(label, monday, sunday) of the ISO week before the one containing `today`."""
    return _week(today - timedelta(days=today.weekday() + 7))


def _week(monday: date) -> tuple[str, date, date]:
    iso = monday.isocalendar()
    return f"{iso.year}-W{iso.week:02d}", monday, monday + timedelta(days=6)


def is_simulated(path: Path) -> bool:
    return SIMULATED_MARKER in path.read_text(encoding="utf-8")


def write_weekly(
    conn: sqlite3.Connection,
    sources: list[Source],
    today: date,
    *,
    docs_dir: Path = DOCS_DIR,
) -> list[Path]:
    """Write the last completed week, then repair recent lede-less weeks."""
    _, last_monday, _ = last_completed_week(today)
    written: list[Path] = []
    for back in range(REPAIR_WEEKS):
        label, monday, sunday = _week(last_monday - timedelta(weeks=back))
        target = docs_dir / "archive" / f"{label}.html"
        if not target.exists() or is_simulated(target):
            if back > 0:
                continue  # older missing/simulated weeks stay as they are
            lede_required = False
        elif LEDE_MARKER in target.read_text(encoding="utf-8"):
            continue
        else:
            lede_required = True  # real page without lede: rewrite only with one
        path = _write_week(conn, sources, label, monday, sunday, target, lede_required)
        if path:
            written.append(path)
    return written


def _write_week(
    conn: sqlite3.Connection,
    sources: list[Source],
    label: str,
    monday: date,
    sunday: date,
    target: Path,
    lede_required: bool,
) -> Path | None:

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
    if lede_required and not headline:
        log.info("weekly %s: still no lede, keeping the existing page", label)
        return None
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
