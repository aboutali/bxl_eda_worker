# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Daily digest of EU foreign-policy, Middle East and sanctions developments out of Brussels, framed for a Swiss-confederation reader (SECO / EDA-FDFA / Federal Council). The worker is a single batch process that runs once a day, polls a curated set of sources, classifies items, optionally enriches them with an LLM, and writes both a markdown digest and a static HTML site.

## Commands

```powershell
# Setup (Windows PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,headless,llm]"
playwright install chromium     # ~110 MB; needed for the Council source

# Run the worker
python -m bxl_eda_worker run                   # default 24h window
python -m bxl_eda_worker run --window-hours 72 # wider catch-up window
python -m bxl_eda_worker run --skip-headless   # skip Playwright sources (fast dry run)

# Tests
pytest tests/                                  # full suite
pytest tests/test_classify.py                  # one file
pytest tests/test_classify.py::test_name -v    # one test
```

The worker writes to three locations (relative to repo root):
- `digests/YYYY-MM-DD.md` — markdown digest (per-day file)
- `docs/index.html`, `docs/archive/YYYY-MM-DD.html`, `docs/archive/index.html` — GitHub Pages site
- `data/items.sqlite` — dedup store (90-day retention)
- `data/llm_cache.sqlite` — per-URL LLM enrichment cache

`data/` and `digests/` are gitignored as runtime output. `docs/` is **intentionally tracked** because GitHub Pages serves from it; only `docs/style.css` is hand-edited, the rest is regenerated each run by the daily Actions workflow.

## Architecture

### Pipeline (single pass per run)

`worker.run()` in `src/bxl_eda_worker/worker.py` orchestrates a strict sequence:

1. **Load sources** from `sources.toml` (`config.load_sources`).
2. **Fetch** by source `type`: `rss` → `fetchers.rss`, `eeas_html` → `fetchers.html` (HTML scrape with `selectolax`), `headless_html` → `fetchers.headless` (Playwright Chromium, optional, gracefully skipped on import error or `--skip-headless`).
3. **Classify** with the keyword classifier (`classify.classify`) → assigns `topics`, `regions`, `swiss_relevance`. **Filter** out items with no matching topics (`is_relevant`).
4. **LLM-enrich** (`analyze.enrich_items`) — *before* persisting — so LLM-derived fields (`summary_oneliner`, `swiss_rationale`, `importance`, refined topics/regions/swiss_relevance) are stored. No-ops if `ANTHROPIC_API_KEY` unset or `anthropic` SDK missing.
5. **Persist + dedup** in SQLite (`storage.upsert_items`), prune > 90 days.
6. **Compose headline** (`analyze.compose_headline`) — single 3-5 sentence narrative paragraph synthesizing the day, prepended to the digest.
7. **Render** markdown (`digest.render` → `write_digest`) **and** HTML (`render_html.render_html` → `write_html_outputs` → `refresh_archive_index`).

The HTML renderer deliberately reuses `digest.py`'s ordering helpers (`CATEGORY_ORDER`, `TOPIC_ORDER`, `_dedupe_by_title`, `_sort_for_section`) so markdown and HTML outputs stay structurally identical.

### Two classifiers, layered

The keyword classifier (`classify.py`, with keyword sets in `config.py`) runs first as a *gate* — items with zero topic matches are dropped before any LLM call, capping cost. The LLM (`analyze.py`, default `claude-opus-4-7`) then runs on survivors and **may overwrite** `topics`, `regions`, `swiss_relevance` with sharper values, plus add the new fields (`summary_oneliner`, `swiss_rationale`, `importance`). The keyword sets must use word-bounded matching (`\b…\b`) to avoid e.g. "Romanian" matching "Oman" — see the regex compilation in `classify._compile`.

### Storage & migrations

`storage.py` uses a hand-rolled additive migration list (`_MIGRATIONS`) that adds columns via `ALTER TABLE` if absent. When you add a field to `Item`, append a migration entry **and** update the schema constant + the SELECT/INSERT lists in `upsert_items` / `items_in_window` / `_row_to_item`. The `ON CONFLICT(url) DO UPDATE` clause is intentionally guarded (`WHERE excluded.summary_oneliner != '' AND items.summary_oneliner = ''`) so a re-fetched item won't lose existing enrichment if the new fetch happens before LLM enrichment.

The LLM cache (`llm_cache.py`) keys on `(url, prompt_version, model)`. Bump `PROMPT_VERSION` to invalidate all cached enrichments after a system-prompt change.

### Source taxonomy

Sources live in `sources.toml`. Each has a `type` (driving which fetcher runs), a `category` (driving digest grouping — `eu_institution`, `swiss_official`, `press_eu`, `press_swiss`, `press_intl`, `think_tank`), a `weight` (1–3, breaks ties in section ordering), and optionally `selector` / `title_selector` / `badge` for `headless_html` sources. `config.load_sources` validates `category` against the `CATEGORIES` tuple — keep them in sync.

The 🇨🇭 highlights section pulls from any item with `swiss_relevance=True`, which the classifier sets when it finds Swiss keywords **or** when the item is a sanctions item (SECO routinely decides on alignment with EU restrictive measures — that's the editorial reason).

## Operational notes

- **Headless is best-effort.** The `headless` extra is optional; if `playwright` isn't installed the worker logs a warning and continues. `--skip-headless` short-circuits even when it is installed (useful for fast iteration).
- **LLM enrichment is best-effort.** Missing `ANTHROPIC_API_KEY` or `anthropic` SDK → keyword classifier alone, no headline. The site still builds.
- **GitHub Actions** (`.github/workflows/daily-digest.yml`) runs at 06:00 UTC, caches both `data/` (so each run is a true 24h delta) and `~/.cache/ms-playwright` (so Chromium isn't re-downloaded), then commits regenerated `docs/` back to `main`. The bot commit is created by `github-actions[bot]`; do not amend or rewrite those commits during normal local work.
- **What's deliberately not wired up** (per README): admin.ch / SECO / EDA official sites (JS-hydrated, selectors not yet reverse-engineered), Council meetings calendar (slow XHRs), Euractiv (HTTP 403). Don't add these without a working selector / fetch path.
