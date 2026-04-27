# bxl_eda_worker

Daily digest of EU foreign-policy, sanctions and Middle East developments out of Brussels — built for a Swiss-confederation reader (SECO/EDA lens).

Polls EEAS, Council of the EU (incl. FAC calendar), European Parliament & AFET, the Commission press corner, and Politico Europe. Filters items by topic (sanctions / Middle East / high-level FP), flags those with likely SECO-alignment relevance, and writes a markdown digest under `digests/YYYY-MM-DD.md`.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## Run

```powershell
# Fetch all sources, classify, store, write today's digest:
python -m bxl_eda_worker run

# Custom lookback window (e.g. last 72h after a long weekend):
python -m bxl_eda_worker run --window-hours 72
```

The digest lands in `digests/YYYY-MM-DD.md`. The dedup store lives in `data/items.sqlite` and keeps 90 days of history.

## Schedule it (Windows Task Scheduler)

Create a daily task that runs at ~07:00 CET:

```powershell
$action  = New-ScheduledTaskAction -Execute "$PWD\.venv\Scripts\python.exe" -Argument "-m bxl_eda_worker run" -WorkingDirectory $PWD
$trigger = New-ScheduledTaskTrigger -Daily -At 7:00am
Register-ScheduledTask -TaskName "bxl_eda_worker" -Action $action -Trigger $trigger
```

## Adding or fixing sources

Edit `sources.toml`. Each entry needs `id`, `name`, `type = "rss"`, `url`, and an optional `weight` (1–3, higher floats to the top within a topic). Only RSS is wired up today; non-RSS sources (EUR-Lex CFSP listings, scraped Council pages) are an obvious next step.

## What gets flagged for Switzerland

- Any item that mentions Switzerland, SECO, FDFA/EDA, or neutrality directly.
- Any item classified as **sanctions** — SECO routinely decides on alignment with new EU restrictive measures, so these surface in a dedicated 🇨🇭 section at the top of the digest.

## Limitations (be honest)

- **Council of the EU is not currently polled.** Both `consilium.europa.eu` RSS endpoints (press releases + meetings calendar, where FAC outcomes land) returned HTTP 403 with a "Browser check" interstitial — they're behind bot protection that a plain HTTP client cannot bypass. The disabled entries are left in `sources.toml` as a reminder. Workarounds: (a) drive a headless browser (Playwright) for those URLs, (b) lean on Commission press corner + Politico, which both surface FAC conclusions when they land. Decide based on how much you care about *first-source* Council coverage vs *next-day* secondary coverage.
- **EEAS press material has no useful date in the listing.** EEAS retired its public RSS; we scrape the listing page, but the listing exposes only title+link, not publish dates. New items appear in the digest the first time they're seen and are deduped by URL afterwards. If you want true publish dates, we'd need to fetch each item page (36 extra requests per poll).
- **Classifier is keyword-based, not semantic.** Word-bounded matching avoids the obvious false positives ("Romanian" no longer matches "Oman"), but you'll still see false positives on, e.g., "Russia" in an unrelated context. Tune keyword sets in `src/bxl_eda_worker/config.py`.
- **Politico RSS gives headlines + short excerpts only;** full text is paywalled.
- **No alerting yet** — single daily run, single output file.
