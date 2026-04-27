from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from bxl_eda_worker.config import Source
from bxl_eda_worker.models import Item

log = logging.getLogger(__name__)

USER_AGENT = "bxl_eda_worker/0.1 (+https://github.com/aboutali/bxl_eda_worker)"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def fetch_rss(source: Source, *, client: httpx.Client | None = None) -> list[Item]:
    own_client = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    try:
        resp = client.get(source.url, follow_redirects=True)
    except httpx.HTTPError as exc:
        log.warning("fetch failed for %s: %s", source.id, exc)
        return []
    finally:
        if own_client:
            client.close()

    if resp.status_code >= 400:
        log.warning("fetch %s returned %s", source.id, resp.status_code)
        return []

    parsed = feedparser.parse(resp.content)
    now = datetime.now(timezone.utc)
    items: list[Item] = []
    for entry in parsed.entries:
        url = getattr(entry, "link", None)
        title = getattr(entry, "title", None)
        if not url or not title:
            continue
        items.append(
            Item(
                url=url,
                source=source.id,
                title=title.strip(),
                summary=_clean_summary(getattr(entry, "summary", "")),
                published_at=_parse_date(entry),
                fetched_at=now,
            )
        )
    return items


def _parse_date(entry) -> datetime | None:
    for attr in ("published", "updated", "created"):
        raw = getattr(entry, attr, None)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            continue
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def _clean_summary(html: str) -> str:
    if not html:
        return ""
    # Cheap strip — feedparser already gives us text-ish content for most feeds.
    from selectolax.parser import HTMLParser

    text = HTMLParser(html).text(separator=" ").strip()
    return " ".join(text.split())[:600]
