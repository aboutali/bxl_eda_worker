from __future__ import annotations

from datetime import date, timedelta

import httpx

from bxl_eda_worker.config import Source
from bxl_eda_worker.fetchers import ep_open_data

SOURCE = Source(id="ep_adopted", name="EP", type="ep_open_data", url="https://x", category="eu_institution")


def _record(identifier: str, title: str, day: date) -> dict:
    return {
        "identifier": identifier,
        "document_date": day.isoformat(),
        "title_dcterms": {"en": title},
        "is_realized_by": [{"title_alternative": {"en": f"European Parliament resolution on {title.lower()}"}}],
    }


def test_fetch_keeps_recent_texts_newest_first(monkeypatch):
    today = date.today()
    records = {
        "TA-10-2026-0380": _record("TA-10-2026-0380", "Ukrainian children deported to Russia", today),
        "TA-10-2026-0099": _record("TA-10-2026-0099", "Old resolution edited again", today - timedelta(days=60)),
        "TA-10-2026-0379": {},  # detail request failed
    }
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/feed"):
            assert request.url.params["timeframe"] == "one-week"
            data = [{"identifier": i} for i in ("TA-10-2026-0099", "TA-10-2026-0380", "TA-10-2026-0379", "CRE-10-2026-01-19")]
            return httpx.Response(200, json={"data": data})
        assert request.url.params["language"] == "en"
        identifier = request.url.path.rsplit("/", 1)[1]
        if not records[identifier]:
            return httpx.Response(500)
        return httpx.Response(200, json={"data": [records[identifier]]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        items = ep_open_data.fetch_ep_adopted_texts(SOURCE, client=client)

    assert [i.title for i in items] == ["Ukrainian children deported to Russia"]
    it = items[0]
    assert it.url == "https://www.europarl.europa.eu/doceo/document/TA-10-2026-0380_EN.html"
    assert it.summary == "European Parliament resolution on ukrainian children deported to russia"
    assert it.published_at is None and it.source == "ep_adopted"
    assert not any("CRE-10" in p for p in seen)


def test_fetch_feed_error_returns_nothing(caplog):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as client:
        assert ep_open_data.fetch_ep_adopted_texts(SOURCE, client=client) == []
    assert "returned 503" in caplog.text


def test_newest_texts_sort_by_term_year_number():
    ids = ["TA-9-2024-0112", "TA-10-2026-0010", "TA-10-2026-0380", "TA-10-2025-0400"]
    assert sorted(ids, key=ep_open_data._sequence, reverse=True) == [
        "TA-10-2026-0380", "TA-10-2026-0010", "TA-10-2025-0400", "TA-9-2024-0112",
    ]
