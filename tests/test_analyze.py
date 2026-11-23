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
    fake_client.beta.messages.parse.return_value = fake_response

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
    fake_client.beta.messages.parse.assert_called_once()
    kwargs = fake_client.beta.messages.parse.call_args.kwargs
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["output_config"] == {"effort": "medium"}
    assert kwargs["fallbacks"] == "default"
    assert kwargs["betas"] == ["server-side-fallback-2026-07-01"]


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
    fake_client.beta.messages.parse.return_value = fake_response

    with patch("bxl_eda_worker.analyze._client", return_value=fake_client):
        enrich_items([_item("https://t/cached", "X")])
        # Second call with the same URL should hit cache, not the API.
        enrich_items([_item("https://t/cached", "X")])

    assert fake_client.beta.messages.parse.call_count == 1


def test_enrich_failure_skips_item_does_not_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "bxl_eda_worker.llm_cache._DB_PATH", tmp_path / "llm_cache.sqlite"
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")

    fake_client = MagicMock()
    fake_client.beta.messages.parse.side_effect = RuntimeError("transient API failure")

    with patch("bxl_eda_worker.analyze._client", return_value=fake_client):
        items = [_item("https://t/fail", "X")]
        enrich_items(items)  # must not raise

    assert items[0].summary_oneliner == ""  # no enrichment, but not crashed


def test_mostly_failing_enrichment_raises_ci_warning(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("bxl_eda_worker.llm_cache._DB_PATH", tmp_path / "llm_cache.sqlite")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    fake_client = MagicMock()
    fake_client.beta.messages.parse.side_effect = RuntimeError("credit balance is too low")

    with patch("bxl_eda_worker.analyze._client", return_value=fake_client):
        enrich_items([_item("https://t/a", "A"), _item("https://t/b", "B")])

    out = capsys.readouterr().out
    assert "::warning title=LLM enrichment failing::2 of 2 enrichment calls failed" in out
    assert "credit balance is too low" in out


def test_weekly_headline_falls_back_to_titles(monkeypatch):
    from bxl_eda_worker.analyze import compose_headline

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    block = MagicMock()
    block.type, block.text = "text", "Week lede."
    resp.content = [block]
    fake_client = MagicMock()
    fake_client.beta.messages.create.return_value = resp
    items = [_item("https://t/a", "Council lists Iranian officials")]

    with patch("bxl_eda_worker.analyze._client", return_value=fake_client):
        assert compose_headline(items) == ""  # daily: no enrichment, no lede
        assert compose_headline(items, weekly=True, period_label="the week 2026-W47") == "Week lede."

    sent = fake_client.beta.messages.create.call_args.kwargs
    assert "Council lists Iranian officials" in sent["messages"][0]["content"]
    assert sent["output_config"] == {"effort": "medium"}
