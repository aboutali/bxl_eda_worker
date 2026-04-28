"""One-shot backfill that invents a fictitious weekly archive for 2026-W01..

Calls Opus 4.7 once per week to generate ~15 plausible items and a synthesis
headline, then writes each as docs/archive/2026-WXX.html. Idempotent — weeks
that already have a file are skipped. Does NOT touch the SQLite store, so the
daily cron's dedup window stays clean.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from bxl_eda_worker.config import load_sources
from bxl_eda_worker.models import Item, Topic
from bxl_eda_worker.render_html import (
    DOCS_DIR,
    refresh_archive_index,
    render_archive_index,
    render_html,
)

log = logging.getLogger(__name__)

MODEL = os.getenv("BXL_LLM_MODEL", "claude-opus-4-7")
WEEK_ITEMS_MAX_TOKENS = 8000
WEEK_HEADLINE_MAX_TOKENS = 4096

SourceId = Literal[
    "eeas_press", "council_press", "commission_press",
    "ep_news", "ep_afet", "ep_sede", "ep_droi", "ep_inta",
    "ep_deve", "ep_dpal", "ep_dmas", "ep_dmag", "ep_dmed",
    "politico_eu", "euobserver",
    "nzz_intl", "tagi", "srf_intl",
    "lmd_recents",
    "ecfr", "bruegel",
]


class FictitiousItem(BaseModel):
    title: str = Field(description="Realistic press-release / article headline.")
    source_id: SourceId = Field(description="Which source published this. Use the 18 source ids verbatim.")
    iso_date: str = Field(description="Publish date, YYYY-MM-DD, must fall within the week's range.")
    summary_oneliner: str = Field(description="One terse sentence, ≤30 words. State what happened and why it matters.")
    topics: list[Topic] = Field(description="From {sanctions, middle_east, foreign_policy}; empty list if none truly apply.")
    regions: list[str] = Field(description="Lowercase country/region keywords (e.g. 'iran', 'gaza'). Empty if none.")
    swiss_relevance: bool
    swiss_rationale: str = Field(description="One clause if swiss_relevance, else empty.")
    importance: int = Field(ge=1, le=5)


class WeekSeed(BaseModel):
    items: list[FictitiousItem]


SYSTEM_PROMPT = """\
You are seeding a fictitious-but-plausible archive of weekly EU foreign-policy \
digests for a Swiss-confederation desk reader (SECO / FDFA-EDA / Federal \
Council). For the week below, invent 13–17 realistic items.

Real 2026 figures you should use:
- António Costa (President of the European Council)
- Ursula von der Leyen (Commission President)
- Kaja Kallas (High Representative / Vice-President for Foreign Affairs)
- Roxana Mînzatu, Andrius Kubilius, Maroš Šefčovič, Magnus Brunner, etc. (Commissioners)

Mix categories realistically:
- ~40% EU institutions (eeas_press, council_press, commission_press, ep_afet, ep_sede, ep_droi, ep_inta, ep_deve, ep_dpal, ep_dmas, ep_dmag, ep_dmed, ep_news)
- ~20% Brussels press (politico_eu, euobserver)
- ~20% Swiss press (nzz_intl, tagi, srf_intl)
- ~10% International press (lmd_recents)
- ~10% Think tanks (ecfr, bruegel)

Mix topics roughly evenly across sanctions, middle_east, and foreign_policy. \
3–5 items per week should have swiss_relevance true (sanctions packages SECO \
must align with, joint statements Switzerland might co-sign, Swiss persons \
or firms named).

Vary the narrative thread week-to-week — don't repeat the same story arc. \
Use real institutions and plausible event types: FAC conclusions, Council \
restrictive-measures regulations, HR/VP statements, Commission press \
remarks, AFET committee votes, Politico Brussels Playbook items, NZZ \
foreign-policy analyses, ECFR briefs.

Calibrate importance ruthlessly — most items 2 or 3, only the genuinely \
significant week-defining stories at 4 or 5.
"""

HEADLINE_SYSTEM = """\
You are writing the lede for a Swiss-confederation foreign-policy weekly \
digest. Given the items below, write a single paragraph of 3–5 sentences \
synthesizing what mattered this week. Lead with the most significant story. \
Connect related items where it adds insight. Where Swiss positioning is \
implicated, flag it. Tone: tight, factual, intelligence-brief register. \
No 'this week saw' / 'in a major development'. Plain prose, no headings.
"""


# ─── Public API ─────────────────────────────────────────────────────────────


def seed_archive(*, force: bool = False) -> int:
    """Generate weekly archive HTML for 2026-W01 through current-1.

    Returns count of weeks written. Skips weeks already on disk unless force=True.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    client = _client()
    if client is None:
        log.error("ANTHROPIC_API_KEY required for archive seeding — aborting")
        return 0

    sources = load_sources()
    archive_dir = DOCS_DIR / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for week_label, monday, sunday in _weeks_to_seed():
        target = archive_dir / f"{week_label}.html"
        if target.exists() and not force:
            log.info("%s: already exists, skipping", week_label)
            continue

        log.info("%s: generating items (%s → %s)", week_label, monday, sunday)
        items = _generate_week_items(client, week_label, monday, sunday, sources)
        if not items:
            log.warning("%s: no items returned, skipping", week_label)
            continue
        log.info("%s: composing headline over %d items", week_label, len(items))
        headline = _compose_week_headline(client, week_label, items)

        window_start = datetime.combine(monday, time.min, tzinfo=timezone.utc)
        window_end = datetime.combine(sunday, time.max, tzinfo=timezone.utc)
        body = render_html(
            items, sources,
            window_start=window_start, window_end=window_end,
            headline=headline,
        )
        # Inject a "simulated" disclaimer banner so it's clear in the source.
        body = body.replace(
            "<main>",
            '<main>\n<aside class="simulated">Simulated weekly digest '
            f'({week_label}, {monday}–{sunday}) — generated as design-fidelity '
            'backfill, not a record of real reporting.</aside>',
            1,
        )
        target.write_text(body, encoding="utf-8")
        written += 1
        log.info("%s: wrote %s", week_label, target)

    refresh_archive_index()
    return written


# ─── Internals ──────────────────────────────────────────────────────────────


def _weeks_to_seed():
    """Yield (label, monday, sunday) for 2026-W01 through last completed week."""
    today = datetime.now(timezone.utc).date()
    cur_year, cur_week, _ = today.isocalendar()
    week = 1
    while True:
        try:
            monday = date.fromisocalendar(2026, week, 1)
            sunday = date.fromisocalendar(2026, week, 7)
        except ValueError:
            return
        # Stop before current week (don't conflict with daily cron).
        iso_year, iso_week, _ = sunday.isocalendar()
        if (iso_year, iso_week) >= (cur_year, cur_week):
            return
        yield (f"2026-W{week:02d}", monday, sunday)
        week += 1
        if week > 53:
            return


def _generate_week_items(client, week_label, monday, sunday, sources) -> list[Item]:
    user_text = (
        f"Week: {week_label} ({monday} → {sunday})\n\n"
        f"Generate 13–17 plausible items for this week."
    )
    try:
        resp = client.messages.parse(
            model=MODEL,
            max_tokens=WEEK_ITEMS_MAX_TOKENS,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_text}],
            output_format=WeekSeed,
        )
    except Exception as exc:
        log.warning("%s: items generation failed: %s", week_label, exc)
        return []

    source_ids = {s.id for s in sources}
    by_id = {s.id: s for s in sources}
    items: list[Item] = []
    for i, fi in enumerate(resp.parsed_output.items):
        if fi.source_id not in source_ids:
            continue
        try:
            published = datetime.fromisoformat(fi.iso_date).replace(tzinfo=timezone.utc)
        except ValueError:
            published = datetime.combine(monday, time(9, 0), tzinfo=timezone.utc)
        items.append(Item(
            url=f"https://example.test/seed/{week_label}/{fi.source_id}-{i:02d}",
            source=fi.source_id,
            category=by_id[fi.source_id].category,
            title=fi.title,
            summary="",
            language=by_id[fi.source_id].language,
            published_at=published,
            fetched_at=datetime.now(timezone.utc),
            topics=fi.topics,
            regions=sorted(set(fi.regions)),
            swiss_relevance=fi.swiss_relevance,
            summary_oneliner=fi.summary_oneliner,
            swiss_rationale=fi.swiss_rationale,
            importance=fi.importance,
        ))
    return items


def _compose_week_headline(client, week_label, items: list[Item]) -> str:
    ranked = sorted(items, key=lambda it: -(it.importance or 0))[:25]
    user_message = (
        f"Items from {week_label}:\n\n"
        + "\n".join(
            f"- [importance {it.importance}, "
            f"{'🇨🇭 ' if it.swiss_relevance else ''}{', '.join(it.topics) or 'unclassified'}] "
            f"{it.summary_oneliner}"
            for it in ranked
        )
    )
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=WEEK_HEADLINE_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=HEADLINE_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:
        log.warning("%s: headline generation failed: %s", week_label, exc)
        return ""
    text_blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return " ".join(t.strip() for t in text_blocks if t.strip())


def _client():
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        log.error("anthropic SDK not installed — run `pip install -e \".[llm]\"`")
        return None
    return Anthropic()
