"""Configuration fencing avoids database access until explicit worker enable."""
from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from services import google_business_scheduler as scheduler
from services.google_business_management import window


@pytest.mark.asyncio
@pytest.mark.parametrize('flag,cutoff', [(None, None), ('false', '2026-11-01T00:00:00Z'), ('true', None), ('true', '2026-11-01T00:00:00'), ('true', 'invalid')])
async def test_scheduler_cannot_touch_database_without_complete_explicit_configuration(monkeypatch, flag, cutoff):
    for name, value in [('T24_GBP_SCHEDULER_ENABLED', flag), ('T24_GBP_SCHEDULER_ACTIVATION_FROM', cutoff)]:
        if value is None: monkeypatch.delenv(name, raising=False)
        else: monkeypatch.setenv(name, value)
    def sessions(): pytest.fail('disabled scheduler opened a database session')
    assert await scheduler.run_tick(sessions=sessions) == {'stage': 'disabled', 'processed': 0}
    monkeypatch.setattr(scheduler.asyncio, 'create_task', lambda *args: pytest.fail('disabled worker created'))
    assert scheduler.start_scheduler() is None


@pytest.mark.asyncio
async def test_future_activation_does_not_open_database_or_catch_up_earlier_jobs(monkeypatch):
    monkeypatch.setenv('T24_GBP_SCHEDULER_ENABLED', 'true')
    monkeypatch.setenv('T24_GBP_SCHEDULER_ACTIVATION_FROM', '2026-11-02T00:00:00Z')
    assert await scheduler.run_tick(sessions=lambda: pytest.fail('not yet active'), clock=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc)) == {'stage': 'waiting_activation', 'processed': 0}


def test_offset_activation_is_normalized_to_an_explicit_utc_instant(monkeypatch):
    monkeypatch.setenv('T24_GBP_SCHEDULER_ENABLED', 'true')
    monkeypatch.setenv('T24_GBP_SCHEDULER_ACTIVATION_FROM', '2026-11-01T01:30:00-04:00')
    assert scheduler.configuration() == {'enabled': True, 'activation_from': '2026-11-01T05:30:00+00:00'}


@pytest.mark.parametrize('start,end', [('2026-11-01T00:00:00', '2026-11-02T00:00:00Z'), ('2026-11-02T00:00:00Z', '2026-11-01T00:00:00Z'), ('2026-01-01T00:00:00Z', '2028-01-01T00:00:00Z')])
def test_reports_require_bounded_explicit_time_ranges(start, end):
    with pytest.raises(HTTPException): window(start, end, 366)
