"""LLM-based enrichment and daily headline composition.

Runs on top of the keyword classifier. If `ANTHROPIC_API_KEY` is unset or the
`anthropic` SDK isn't installed, both functions log a warning and no-op so the
rest of the pipeline still produces a digest.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from bxl_eda_worker import llm_cache
from bxl_eda_worker.models import Item, ItemEnrichment

if TYPE_CHECKING:
    from anthropic import Anthropic

log = logging.getLogger(__name__)

# Defaults to Opus 4.7 per skill guidance (most capable; user can override).
MODEL = os.getenv("BXL_LLM_MODEL", "claude-opus-4-7")

# Cap headline output; full thinking is allowed via adaptive thinking + max_tokens
# headroom — Opus 4.7 truncates output at high effort with low max_tokens.
HEADLINE_MAX_TOKENS = 4096
ITEM_MAX_TOKENS = 1024

SYSTEM_PROMPT_ITEM = """\
You triage news items for a Swiss-confederation foreign-policy desk reader \
(SECO, FDFA/EDA, Federal Council). Their job is to track EU developments out \
of Brussels — Foreign Affairs Council, EEAS / HR-VP statements, Council \
sanctions packages, Middle East, broad EU foreign policy — with a Swiss lens.

For each item, return:
- summary_oneliner: one terse sentence, ≤30 words, no preamble. State what \
happened, by whom, and why it matters. Drop adjectives.
- topics: from {sanctions, middle_east, foreign_policy}. Include only those \
that genuinely apply — empty list if none.
- regions: lowercase country/region keywords mentioned (e.g. 'iran', 'gaza', \
'russia', 'sudan'). Empty if none.
- swiss_relevance: true iff a SECO/EDA reader needs this on their radar — \
typically: any EU sanctions package (SECO routinely decides on alignment), any \
joint statement Switzerland might co-sign or notably not, any Swiss person/firm \
mentioned, anything touching neutrality.
- swiss_rationale: one clause if relevant, empty string otherwise.
- importance: 1=routine boilerplate, 3=normal news, 5=front-page-FT material \
(major sanctions packages, FAC conclusions on a war, leader-level summit \
outcomes). Calibrate against EU foreign-policy daily news flow.

Be ruthless about importance — most items are 2 or 3. Reserve 5 for genuinely \
significant events.
"""

SYSTEM_PROMPT_HEADLINE = """\
You are writing the lede for a Swiss-confederation foreign-policy daily \
digest covering EU developments out of Brussels.

Read the bulleted items below (sorted by importance). Write a single paragraph \
of 3–5 sentences synthesizing what mattered today. Lead with the most \
significant story. Connect related items where it adds insight (e.g. a \
sanctions package alongside a related FAC statement). Where Swiss \
positioning is implicated (sanctions to align with, statements to co-sign), \
flag it explicitly.

Tone: tight, factual, intelligence-brief register. No adjectives like \
'unprecedented', 'historic', 'massive'. No 'today saw' / 'in the world of'. \
Just facts and connections. Markdown-clean — plain prose, no bullet points, \
no headings.
"""


# ─── Public API ─────────────────────────────────────────────────────────────


def enrich_items(items: list[Item]) -> list[Item]:
    """Annotate each item in-place with LLM-derived fields. Cached by URL."""
    if not items:
        return items
    client = _client()
    if client is None:
        return items

    cache_hits = 0
    cache_misses = 0
    failures = 0
    for it in items:
        cached = llm_cache.get(it.url, MODEL)
        if cached is not None:
            _apply(it, cached)
            cache_hits += 1
            continue
        try:
            payload = _enrich_one(client, it)
        except Exception as exc:
            log.warning("enrichment failed for %s: %s", it.url, exc)
            failures += 1
            continue
        llm_cache.put(it.url, MODEL, payload)
        _apply(it, payload)
        cache_misses += 1
    log.info(
        "enrichment: %d cached, %d new, %d failed (model=%s)",
        cache_hits, cache_misses, failures, MODEL,
    )
    return items


def compose_headline(items: list[Item]) -> str:
    """Return a 3–5 sentence narrative paragraph. Empty string if no LLM."""
    if not items:
        return ""
    client = _client()
    if client is None:
        return ""
    # Sort by importance; cap to keep prompt size tractable.
    ranked = sorted(
        items,
        key=lambda it: (-(it.importance or 0), -(it.swiss_relevance)),
    )[:25]
    if not any(it.summary_oneliner for it in ranked):
        # Nothing useful to summarize — items weren't enriched.
        return ""

    prompt_lines = [
        f"- [importance {it.importance or '?'}, "
        f"{'🇨🇭 ' if it.swiss_relevance else ''}{', '.join(it.topics) or 'unclassified'}] "
        f"{it.summary_oneliner or it.title}"
        for it in ranked
    ]
    user_message = "Items from the last 24h:\n\n" + "\n".join(prompt_lines)

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=HEADLINE_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            system=SYSTEM_PROMPT_HEADLINE,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:
        log.warning("headline generation failed: %s", exc)
        return ""

    text_blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    headline = " ".join(t.strip() for t in text_blocks if t.strip())
    log.info(
        "headline composed: %d chars (input=%s, output=%s, cache_read=%s)",
        len(headline),
        resp.usage.input_tokens,
        resp.usage.output_tokens,
        getattr(resp.usage, "cache_read_input_tokens", 0),
    )
    return headline


# ─── Internals ──────────────────────────────────────────────────────────────


def _client():
    if not os.getenv("ANTHROPIC_API_KEY"):
        log.info("ANTHROPIC_API_KEY not set — skipping LLM enrichment")
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        log.warning("anthropic SDK not installed — run `pip install -e \".[llm]\"`")
        return None
    return Anthropic()


def _enrich_one(client: "Anthropic", item: Item) -> dict:
    user_text = (
        f"Source: {item.source} ({item.category})\n"
        f"Language: {item.language}\n"
        f"Title: {item.title}\n"
        f"Summary: {item.summary or '(none)'}"
    )
    # Prompt caching on the system block — break-even at 2 calls; we make 30+.
    resp = client.messages.parse(
        model=MODEL,
        max_tokens=ITEM_MAX_TOKENS,
        cache_control={"type": "ephemeral"},
        system=SYSTEM_PROMPT_ITEM,
        messages=[{"role": "user", "content": user_text}],
        output_format=ItemEnrichment,
    )
    return resp.parsed_output.model_dump()


def _apply(it: Item, payload: dict) -> None:
    it.summary_oneliner = payload.get("summary_oneliner", "") or ""
    # LLM may sharpen topics/regions vs the keyword classifier; trust the LLM.
    if "topics" in payload:
        it.topics = payload["topics"]
    if "regions" in payload:
        it.regions = sorted(set(payload["regions"]))
    if "swiss_relevance" in payload:
        it.swiss_relevance = bool(payload["swiss_relevance"])
    it.swiss_rationale = payload.get("swiss_rationale", "") or ""
    it.importance = int(payload.get("importance", 0) or 0)
