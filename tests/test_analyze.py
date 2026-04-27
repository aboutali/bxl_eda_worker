from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from bxl_eda_worker.analyze import compose_headline, enrich_items
from bxl_eda_worker.models import Item, ItemEnrichment


def _item(url: str, title: str, **overrides) -> Item:
    base = dict(
        url=url,
        source="test",
        category="eu_institution",
        title=title,
        summary="placeholder",
        fetched_at=datetime.now(timezone.utc),
        topics=["foreign_policy"],
    )
    base.update(overrides)
    return Item(**base)


def test_enrich_no_op_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    items = [_item("https://t/1", "Some headline")]
    result = enrich_items(items)
    # Items returned unchanged — summary_oneliner stays empty.
    assert result is items
    assert result[0].summary_oneliner == ""
    assert result[0].importance == 0


def test_compose_headline_no_op_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    items = [_item("https://t/1", "Some headline")]
    assert compose_headline(items) == ""


def test_enrich_applies_llm_payload_to_item(monkeypatch, tmp_path):
    # Isolate the cache to a tmp DB so this test doesn't touch real data/.
    monkeypatch.setattr(
        "bxl_eda_worker.llm_cache._DB_PATH", tmp_path / "llm_cache.sqlite"
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")

    fake_enrichment = ItemEnrichment(
        summary_oneliner="Council adopts 17th sanctions package against Russia.",
        topics=["sanctions", "foreign_policy"],
        regions=["russia"],
        swiss_relevance=True,
        swiss_rationale="SECO will decide on alignment.",
        importance=5,
    )
    fake_response = MagicMock()
    fake_response.parsed_output = fake_enrichment

    fake_client = MagicMock()
    fake_client.messages.parse.return_value = fake_response

    with patch("bxl_eda_worker.analyze._client", return_value=fake_client):
        items = [_item("https://t/sanctions", "Council adopts X")]
        enrich_items(items)

    it = items[0]
    assert it.summary_oneliner.startswith("Council adopts 17th")
    assert "sanctions" in it.topics
    assert "russia" in it.regions
    assert it.swiss_relevance is True
    assert it.swiss_rationale == "SECO will decide on alignment."
    assert it.importance == 5
    fake_client.messages.parse.assert_called_once()


def test_enrich_uses_cache_on_second_call(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "bxl_eda_worker.llm_cache._DB_PATH", tmp_path / "llm_cache.sqlite"
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")

    fake_enrichment = ItemEnrichment(
        summary_oneliner="Cached summary.", topics=["sanctions"], regions=[],
        swiss_relevance=False, swiss_rationale="", importance=3,
    )
    fake_response = MagicMock()
    fake_response.parsed_output = fake_enrichment
    fake_client = MagicMock()
    fake_client.messages.parse.return_value = fake_response

    with patch("bxl_eda_worker.analyze._client", return_value=fake_client):
        enrich_items([_item("https://t/cached", "X")])
        # Second call with the same URL should hit cache, not the API.
        enrich_items([_item("https://t/cached", "X")])

    assert fake_client.messages.parse.call_count == 1


def test_enrich_failure_skips_item_does_not_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "bxl_eda_worker.llm_cache._DB_PATH", tmp_path / "llm_cache.sqlite"
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")

    fake_client = MagicMock()
    fake_client.messages.parse.side_effect = RuntimeError("transient API failure")

    with patch("bxl_eda_worker.analyze._client", return_value=fake_client):
        items = [_item("https://t/fail", "X")]
        enrich_items(items)  # must not raise

    assert items[0].summary_oneliner == ""  # no enrichment, but not crashed
