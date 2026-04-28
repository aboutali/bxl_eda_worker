from __future__ import annotations

from datetime import date
from unittest.mock import patch

from bxl_eda_worker.seed import _weeks_to_seed


def test_weeks_to_seed_starts_at_w01_and_stops_before_current(monkeypatch):
    """Yields W01 through (current-1), never including the in-flight week."""
    # Pretend today is 2026-04-28 (Tuesday of W18).
    fake_today = date(2026, 4, 28)

    class _FakeDateTime:
        @staticmethod
        def now(tz=None):
            from datetime import datetime, time, timezone
            return datetime.combine(fake_today, time(12, 0), tzinfo=tz or timezone.utc)

    with patch("bxl_eda_worker.seed.datetime", _FakeDateTime):
        weeks = list(_weeks_to_seed())

    labels = [w[0] for w in weeks]
    assert labels[0] == "2026-W01"
    assert labels[-1] == "2026-W17"
    assert "2026-W18" not in labels  # current week excluded
    assert len(labels) == 17

    # Each tuple: (label, monday, sunday); sunday must be the Saturday + 1
    label, monday, sunday = weeks[0]
    assert label == "2026-W01"
    assert monday == date(2025, 12, 29)  # ISO week 1 of 2026 starts 2025-12-29
    assert sunday == date(2026, 1, 4)


def test_weeks_to_seed_does_not_include_future_weeks(monkeypatch):
    """If today is W02, only W01 should seed."""
    fake_today = date(2026, 1, 8)  # Thursday of W02

    class _FakeDateTime:
        @staticmethod
        def now(tz=None):
            from datetime import datetime, time, timezone
            return datetime.combine(fake_today, time(12, 0), tzinfo=tz or timezone.utc)

    with patch("bxl_eda_worker.seed.datetime", _FakeDateTime):
        weeks = list(_weeks_to_seed())

    assert [w[0] for w in weeks] == ["2026-W01"]
