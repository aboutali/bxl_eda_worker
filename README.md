# bxl_eda_worker

Daily digest of EU foreign-policy, Middle East and sanctions developments out of Brussels — built for a Swiss-confederation reader (SECO/EDA lens).

Polls primary EU sources (EEAS, Council of the EU via headless browser, European Commission, Parliament committees AFET/SEDE/DROI/INTA), Brussels press (Politico, EUobserver), Swiss press (NZZ, Tages-Anzeiger, SRF), French international press (Le Monde Diplomatique), and EU think tanks (ECFR, Bruegel). Filters by topic (sanctions / Middle East / high-level FP), flags items with likely SECO-alignment relevance, and writes a markdown digest under `digests/YYYY-MM-DD.md`.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Core install (RSS + EEAS HTML scrape):
pip install -e .

# Optional: headless browser for Council of the EU (FAC press releases),
# which sits behind a JS anti-bot interstitial.
pip install -e ".[headless]"
playwright install chromium   # ~110 MB

# Optional: LLM enrichment (per-item Opus 4.7 summary/classification
# + a daily synthesis headline at the top of the digest).
pip install -e ".[llm]"
$env:ANTHROPIC_API_KEY = "sk-ant-..."   # or `setx` to persist
```

If you skip the headless install, the worker logs a warning and keeps going with the other sources. You can also force it with `--skip-headless` for a fast dry run.

If you skip the LLM install or don't set `ANTHROPIC_API_KEY`, the worker uses the keyword classifier alone and the digest renders without a top-of-page synthesis headline. Site still builds.

## Run

```powershell
python -m bxl_eda_worker run                      # 24h window
python -m bxl_eda_worker run --window-hours 72    # after a long weekend
python -m bxl_eda_worker run --skip-headless      # fast, no Chromium
```

Output: `digests/YYYY-MM-DD.md`. Dedup store: `data/items.sqlite` (90-day retention).

### Seeding the archive (one-shot, optional)

For design-fidelity backfill, you can generate a fictitious weekly archive covering 2026-W01 through last completed week:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python -m bxl_eda_worker seed-archive
```

This calls Opus 4.7 once per week (~17 weeks × 2 calls ≈ $3–4 one-time) to invent ~15 plausible items + a synthesis headline per week, and writes each as `docs/archive/2026-WXX.html`. Idempotent — already-seeded weeks are skipped (use `--force` to regenerate). Each generated page carries a "Simulated weekly digest" disclaimer in its body. The SQLite dedup store is **not** touched, so the daily cron stays clean.

## Schedule it (Windows Task Scheduler)

Daily 07:00 CET:

```powershell
$action  = New-ScheduledTaskAction -Execute "$PWD\.venv\Scripts\python.exe" -Argument "-m bxl_eda_worker run" -WorkingDirectory $PWD
$trigger = New-ScheduledTaskTrigger -Daily -At 7:00am
Register-ScheduledTask -TaskName "bxl_eda_worker" -Action $action -Trigger $trigger
```

## Hosted version (GitHub Pages)

Each run also writes a static HTML site to `docs/`:

- `docs/index.html` — latest digest (overwritten daily)
- `docs/archive/YYYY-MM-DD.html` — versioned per-day digest
- `docs/archive/index.html` — auto-generated table of contents
- `docs/style.css` — minimal stylesheet (light + dark mode)

A GitHub Actions workflow at `.github/workflows/daily-digest.yml` runs every day at **06:00 UTC**, regenerates the digest in CI (Playwright Chromium included), and commits `docs/` back to `main`. To activate hosting:

1. **Make the repo public** (or upgrade to GitHub Pro — Pages on private repos requires a paid plan).
2. **Enable Pages**: repo Settings → Pages → Source: *Deploy from a branch* → Branch: `main`, Folder: `/docs` → Save.
3. **(Optional) Add the Anthropic key** for the daily synthesis headline + per-item enrichment: repo Settings → Secrets and variables → Actions → New repository secret → name `ANTHROPIC_API_KEY`, value `sk-ant-...`. The workflow already passes it through; without it the worker falls back to the keyword classifier and skips the headline.
4. The site will be at `https://aboutali.github.io/bxl_eda_worker/`.

The workflow uses `actions/cache` to persist `data/items.sqlite` across runs (so the daily digest is a true 24h delta) and to cache the Playwright Chromium download (~110 MB).

You can also trigger a build manually from the Actions tab (`Run workflow`).

## Source taxonomy

Each source carries a `category` that drives digest grouping:

| Category | Sources |
|---|---|
| 🇪🇺 EU institutions | EEAS, Council of the EU (headless), Commission, Parliament (AFET, SEDE, DROI, INTA) |
| 🇨🇭 Swiss confederation | *currently empty — see "What's not yet wired up" below* |
| Brussels press | Politico Europe, EUobserver |
| Swiss press | NZZ International, Tages-Anzeiger, SRF |
| International press | Le Monde Diplomatique |
| Think tanks | ECFR, Bruegel |

The 🇨🇭 Swiss-relevance highlights section at the top of each digest pulls items from any category that mention Switzerland/SECO/EDA/neutrality, plus any sanctions item (since SECO routinely decides on alignment).

## Adding or fixing sources

Edit `sources.toml`. Each entry needs `id`, `name`, `type`, `url`, `category`, plus optional `weight`, `language`, `selector` (for `headless_html`), `title_selector`, `badge`.

## What gets flagged for Switzerland

- Items mentioning **Switzerland, SECO, FDFA/EDA, neutrality, autonomer Nachvollzug** (German, French, Italian variants supported).
- Any item classified as **sanctions** — SECO routinely decides on alignment with new EU restrictive measures, so these surface in a dedicated 🇨🇭 section at the top of the digest.

## What's not yet wired up (be honest)

- **Swiss federal sites** (admin.ch, SECO, EDA): JS-hydrated CMS where the press release listing anchors don't appear in the rendered DOM even after `networkidle` + scroll. Probably a deferred API call triggered by user interaction. Selector reverse-engineering needed. Meanwhile NZZ/Tagi/SRF cover the same announcements with a journalistic angle.
- **Council meetings calendar (FAC dates)**: the page never reaches `networkidle` (constant analytics XHRs) and our `wait_for_selector` poll didn't surface items in 15s. Press releases above carry FAC *outcomes*, which is the higher-signal information; the *when* of the next FAC is secondary. Disabled with a note in `sources.toml`.
- **Euractiv**: bot-blocked (HTTP 403). Could be added as a headless source later.
- **EUR-Lex CFSP feed**: their RSS endpoints return interactive HTML pages; would need scraping.
- **Classifier is keyword-based, not semantic.** Word-bounded matching avoids the obvious false positives ("Romanian" doesn't match "Oman"). Tune keyword sets in `src/bxl_eda_worker/config.py`.
- **Politico RSS** gives headlines + short excerpts only; full text is paywalled.
- **No alerting yet** — single daily run, single output file.

## Dev

```powershell
pip install -e ".[dev,headless]"
pytest tests/
```
