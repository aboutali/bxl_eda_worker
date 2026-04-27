from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx
from selectolax.parser import HTMLParser

from bxl_eda_worker.config import Source
from bxl_eda_worker.models import Item

log = logging.getLogger(__name__)


def fetch_eeas_html(source: Source, *, client: httpx.Client | None = None) -> list[Item]:
    """Scrape EEAS press-material listing.

    EEAS no longer publishes a usable RSS for press material; the listing page
    returns HTML with `h3 a` links per item but no per-item date in the listing.
    We therefore use `fetched_at` as the timestamp — items appear in the digest
    on their first fetch and are deduped by URL afterwards.
    """
    own_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": "Mozilla/5.0 (compatible; bxl_eda_worker/0.1)"},
        timeout=httpx.Timeout(20.0, connect=10.0),
    )
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

    tree = HTMLParser(resp.text)
    now = datetime.now(timezone.utc)
    items: list[Item] = []
    seen: set[str] = set()
    for anchor in tree.css("h3 a"):
        href = anchor.attrs.get("href")
        title = (anchor.text(strip=True) or "").strip()
        if not href or not title:
            continue
        url = urljoin(resp.url and str(resp.url) or source.url, href)
        if url in seen:
            continue
        seen.add(url)
        items.append(
            Item(
                url=url,
                source=source.id,
                title=title,
                summary="",
                published_at=None,
                fetched_at=now,
            )
        )
    return items
