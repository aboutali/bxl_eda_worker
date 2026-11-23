"""European Parliament texts adopted in plenary, from the EP Open Data API.

www.europarl.europa.eu (RSS feeds included) sits behind an AWS WAF that
answers GitHub runners with an empty HTTP 202 challenge, whatever the user
agent. data.europarl.europa.eu serves the same institution's records without
that WAF. Adopted texts carry the plenary resolutions (Iran, Gaza, Ukraine,
urgency resolutions on human rights) this digest is about.

Texts only carry a date, so `published_at` stays empty: like the EEAS scrape,
an item counts from the run that first fetches it (storage keeps the first
`fetched_at`). Texts older than MAX_AGE_DAYS are skipped, so a text the
feed lists again after a later edit does not re-enter the digest.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import httpx

from bxl_eda_worker.config import Source
from bxl_eda_worker.models import Item

log = logging.getLogger(__name__)

API = "https://data.europarl.europa.eu/api/v2"
FORMAT = {"format": "application/ld+json"}
MAX_TEXTS = 25
MAX_AGE_DAYS = 14
WORKERS = 6

_ID_RE = re.compile(r"^TA-(\d+)-(\d{4})-(\d+)$")


def fetch_ep_adopted_texts(source: Source, *, client: httpx.Client) -> list[Item]:
    try:
        resp = client.get(f"{API}/adopted-texts/feed", params={**FORMAT, "timeframe": "one-week"})
    except httpx.HTTPError as exc:
        log.warning("fetch failed for %s: %s", source.id, exc)
        return []
    if resp.status_code != 200:
        log.warning("fetch %s returned %s", source.id, resp.status_code)
        return []

    ids = [d.get("identifier", "") for d in resp.json().get("data", [])]
    newest = sorted((i for i in ids if _ID_RE.match(i)), key=_sequence, reverse=True)[:MAX_TEXTS]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        details = list(pool.map(lambda i: _fetch_text(client, i), newest))

    now = datetime.now(timezone.utc)
    cutoff = now.date() - timedelta(days=MAX_AGE_DAYS)
    items: list[Item] = []
    for identifier, record in zip(newest, details):
        item = _to_item(identifier, record, source, now)
        if item is not None and record and _doc_date(record) >= cutoff:
            items.append(item)
    return items


def _sequence(identifier: str) -> tuple[int, int, int]:
    term, year, number = _ID_RE.match(identifier).groups()
    return int(term), int(year), int(number)


def _fetch_text(client: httpx.Client, identifier: str) -> dict:
    try:
        resp = client.get(f"{API}/adopted-texts/{identifier}", params={**FORMAT, "language": "en"})
        resp.raise_for_status()
        data = resp.json().get("data") or [{}]
        return data[0]
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("ep adopted text %s failed: %s", identifier, exc)
        return {}


def _doc_date(record: dict) -> date:
    try:
        return date.fromisoformat(record.get("document_date", "")[:10])
    except ValueError:
        return date.min


def _to_item(identifier: str, record: dict, source: Source, now: datetime) -> Item | None:
    title = (record.get("title_dcterms") or {}).get("en", "").strip()
    if not title:
        return None
    summary = next(
        (
            r["title_alternative"]["en"].strip()
            for r in record.get("is_realized_by", [])
            if (r.get("title_alternative") or {}).get("en")
        ),
        "",
    )
    return Item(
        url=f"https://www.europarl.europa.eu/doceo/document/{identifier}_EN.html",
        source=source.id,
        category=source.category,
        title=title,
        summary=summary,
        language="en",
        published_at=None,
        fetched_at=now,
    )
