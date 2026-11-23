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

MODEL = os.getenv("BXL_LLM_MODEL", "claude-opus-5-5")
# Opus 5.5 always thinks; effort is the only depth control (its default is
# medium, set explicitly so a model switch can't change it silently).
EFFORT = os.getenv("BXL_LLM_EFFORT", "medium")

# Thinking tokens count against max_tokens, so both caps leave room for it:
# a cut-off item response would fail structured-output parsing.
HEADLINE_MAX_TOKENS = 16000
ITEM_MAX_TOKENS = 8000

# Server-side refusal fallback: if a safety classifier declines a request, the
# API re-runs it on a fallback model chosen by refusal category, in the same
# call. Sent only for models that accept the "default" form.
FALLBACK_MODELS = (
    "claude-opus-5-5", "claude-opus-5", "claude-fable-5-2", "claude-fable-5-1", "claude-sonnet-5-5",
)
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Warn in the Actions run summary when at least this share of LLM calls fail
# (e.g. an empty credit balance), instead of degrading silently.
FAILURE_WARN_SHARE = 0.5

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

SYSTEM_PROMPT_HEADLINE_WEEKLY = (
    SYSTEM_PROMPT_HEADLINE
    .replace("daily", "weekly")
    .replace("what mattered today", "what mattered this week")
)


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
    last_error = ""
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
            last_error = str(exc)
            continue
        llm_cache.put(it.url, MODEL, payload)
        _apply(it, payload)
        cache_misses += 1
    log.info(
        "enrichment: %d cached, %d new, %d failed (model=%s)",
        cache_hits, cache_misses, failures, MODEL,
    )
    attempted = cache_misses + failures
    if failures and failures >= FAILURE_WARN_SHARE * attempted:
        ci_warning(
            "LLM enrichment failing",
            f"{failures} of {attempted} enrichment calls failed (model {MODEL}). "
            f"Last error: {last_error}",
        )
    return items


def compose_headline(
    items: list[Item], *, weekly: bool = False, period_label: str = "the last 24h",
) -> str:
    """Return a 3–5 sentence narrative paragraph. Empty string if no LLM.

    `weekly=True` frames the lede as a weekly synthesis over `period_label`.
    """
    if not items:
        return ""
    client = _client()
    if client is None:
        return ""
    enriched = any(it.summary_oneliner for it in items)
    if not enriched and not weekly:
        # Nothing useful to summarize — items weren't enriched.
        return ""
    # Sort by importance; cap to keep prompt size tractable. A weekly page over
    # unenriched items (LLM down when they were fetched) has no importance to
    # rank by, so it sends every title instead: titles are short.
    cap = (40 if enriched else 250) if weekly else 25
    ranked = sorted(
        items,
        key=lambda it: (-(it.importance or 0), -(it.swiss_relevance)),
    )[:cap]

    prompt_lines = [
        f"- [importance {it.importance or '?'}, "
        f"{'🇨🇭 ' if it.swiss_relevance else ''}{', '.join(it.topics) or 'unclassified'}] "
        f"{it.summary_oneliner or it.title}"
        for it in ranked
    ]
    user_message = f"Items from {period_label}:\n\n" + "\n".join(prompt_lines)
    system = SYSTEM_PROMPT_HEADLINE_WEEKLY if weekly else SYSTEM_PROMPT_HEADLINE

    try:
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=HEADLINE_MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            system=system,
            messages=[{"role": "user", "content": user_message}],
            **fallback_kwargs(),
        )
    except Exception as exc:
        log.warning("headline generation failed: %s", exc)
        ci_warning("LLM headline failed", f"{'Weekly' if weekly else 'Daily'} headline (model {MODEL}): {exc}")
        return ""
    if resp.stop_reason == "refusal":
        log.warning("headline refused (%s)", getattr(resp.stop_details, "category", None))
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


def fallback_kwargs() -> dict:
    if MODEL not in FALLBACK_MODELS:
        return {}
    return {"betas": [FALLBACK_BETA], "fallbacks": "default"}


def ci_warning(title: str, message: str) -> None:
    """Log a warning and, inside GitHub Actions, raise a run annotation."""
    log.warning("%s: %s", title, message)
    if os.getenv("GITHUB_ACTIONS") == "true":
        flat = " ".join(message.split())[:900]
        print(f"::warning title={title}::{flat}", flush=True)


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
    # cache_control goes on the system content block, not as a top-level kwarg.
    resp = client.beta.messages.parse(
        model=MODEL,
        max_tokens=ITEM_MAX_TOKENS,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT_ITEM,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_text}],
        output_config={"effort": EFFORT},
        output_format=ItemEnrichment,
        **fallback_kwargs(),
    )
    if resp.parsed_output is None:
        raise ValueError(f"no structured output (stop_reason={resp.stop_reason})")
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
