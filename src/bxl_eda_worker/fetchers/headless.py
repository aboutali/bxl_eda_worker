"""Playwright-based scraper for sites that:
  - block plain HTTP clients (Council of EU "Browser check" interstitial)
  - or render content client-side (Swiss admin.ch sites)

Heavy dependency. Imported lazily so users without `pip install -e ".[headless]"`
can still run the rest of the worker.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from bxl_eda_worker.config import Source
from bxl_eda_worker.models import Item

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
PAGE_TIMEOUT_MS = 30_000
WAIT_FOR_SELECTOR_TIMEOUT_MS = 15_000


class HeadlessUnavailable(RuntimeError):
    pass


@contextmanager
def browser_context() -> Iterator["object"]:
    """Yield a Playwright BrowserContext. Caller fetches pages via ctx.new_page()."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise HeadlessUnavailable(
            "playwright is not installed; run `pip install -e \".[headless]\"` "
            "and `playwright install chromium`"
        ) from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, locale="en-GB")
        try:
            yield context
        finally:
            context.close()
            browser.close()


def fetch_headless_html(
    source: Source,
    *,
    context=None,
    client=None,  # noqa: ARG001 — kept for fetcher signature compatibility
) -> list[Item]:
    """Render `source.url` in Chromium and extract anchors matching source.selector.

    Pass an existing Playwright context via `context=` to amortize browser
    startup across multiple sources in one run.
    """
    if context is None:
        with browser_context() as ctx:
            return _do_fetch(source, ctx)
    return _do_fetch(source, context)


def _do_fetch(source: Source, context) -> list[Item]:
    page = context.new_page()
    try:
        # Council's calendar page never reaches networkidle (constant analytics
        # XHRs), so we wait for DOM only and then explicitly poll for our target
        # selector. Parse whatever we got even if the wait times out.
        page.goto(source.url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        if source.selector:
            try:
                page.wait_for_selector(
                    source.selector.split(",")[0].strip(),
                    timeout=WAIT_FOR_SELECTOR_TIMEOUT_MS,
                )
            except Exception:
                pass
        else:
            try:
                page.wait_for_load_state("networkidle", timeout=WAIT_FOR_SELECTOR_TIMEOUT_MS)
            except Exception:
                pass
        html = page.content()
        final_url = page.url
    except Exception as exc:
        log.warning("headless fetch failed for %s: %s", source.id, exc)
        return []
    finally:
        page.close()

    selector = source.selector or "h2 a, h3 a, article a"
    return _parse_anchors(html, final_url or source.url, source, selector)


def _parse_anchors(html: str, base_url: str, source: Source, selector: str) -> list[Item]:
    tree = HTMLParser(html)
    now = datetime.now(timezone.utc)
    items: list[Item] = []
    seen: set[str] = set()
    for anchor in tree.css(selector):
        href = anchor.attrs.get("href")
        if not href:
            continue
        title = _extract_title(anchor, source.title_selector)
        if not title or len(title) < 10:
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


def _extract_title(anchor, title_selector: str) -> str:
    if title_selector:
        for inner in anchor.css(title_selector):
            text = (inner.text(strip=True) or "").strip()
            if text:
                return text
    return (anchor.text(strip=True) or "").strip()
