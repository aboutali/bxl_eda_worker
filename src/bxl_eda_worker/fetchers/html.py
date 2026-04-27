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

    EEAS retired its public RSS; we scrape the listing page for `h3 a`. Per-item
    dates are not exposed in the listing, so first-fetched timestamp is used.
    """
    own_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": "Mozilla/5.0 (compatible; bxl_eda_worker/0.2)"},
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

    return _parse_anchors(resp.text, str(resp.url) or source.url, source, "h3 a")


def _parse_anchors(html: str, base_url: str, source: Source, selector: str) -> list[Item]:
    tree = HTMLParser(html)
    now = datetime.now(timezone.utc)
    items: list[Item] = []
    seen: set[str] = set()
    for anchor in tree.css(selector):
        href = anchor.attrs.get("href")
        title = (anchor.text(strip=True) or "").strip()
        if not href or not title or len(title) < 10:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        items.append(
            Item(
                url=url,
                source=source.id,
                category=source.category,
                title=title,
                summary="",
                language=source.language,
                published_at=None,
                fetched_at=now,
            )
        )
    return items


__all__ = ["fetch_eeas_html"]
