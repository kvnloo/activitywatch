"""Synthetic temporal/parse regressions needed before joining independent sources."""
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from scripts import research_flow_metrics as flow
from scripts import research_flow_intervention_analysis as intervention


def event(at, duration, **data):
    return {"timestamp": at, "duration": duration, "data": data}


def test_midnight_splits_into_both_civil_days():
    window = [event("2026-12-31T23:50:00-06:00", 1800, app="Editor", title="PRIVATE")]
    afk = [event("2026-12-31T23:50:00-06:00", 1800, status="not-afk")]
    result = flow.compute_daily(window, afk, tz=ZoneInfo("America/Chicago"))
    assert {d: v["observed_window_seconds"] for d,v in result.items()} == {
        "2026-12-31": 600, "2027-01-01": 1200,
    }
    assert "PRIVATE" not in json.dumps(result)


def test_previous_evening_afk_can_cover_next_morning_window():
    window = [event("2027-01-01T00:00:00-06:00", 1200, app="Editor")]
    afk = [event("2026-12-31T23:50:00-06:00", 1800, status="not-afk")]
    result = flow.compute_daily(window, afk, tz=ZoneInfo("America/Chicago"))
    assert result["2027-01-01"]["observed_window_seconds"] == 1200


@pytest.mark.parametrize("day,next_day,hours", [
    ("2026-03-08", "2026-03-09", 23), ("2026-11-01", "2026-11-02", 25),
    ("2028-02-29", "2028-03-01", 24),
])
def test_actual_elapsed_time_across_dst_and_leap_days(day, next_day, hours):
    tz = ZoneInfo("America/Chicago")
    start = datetime.fromisoformat(day).replace(tzinfo=tz).astimezone(timezone.utc)
    stop = datetime.fromisoformat(next_day).replace(tzinfo=tz).astimezone(timezone.utc)
    duration = (stop-start).total_seconds()
    assert duration == hours*3600
    window = [event(start.isoformat(), duration, app="Editor")]
    afk = [event(start.isoformat(), duration, status="not-afk")]
    result = flow.compute_daily(window, afk, tz=tz)
    assert list(result) == [day]
    assert result[day]["observed_window_seconds"] == hours*3600


def test_invalid_intervals_do_not_crash_or_create_days():
    malformed = [{"timestamp":"PRIVATE", "duration":60}, {},
                 event("2026-10-01T00:00:00Z", 1e308, app="Editor")]
    good = event("2026-10-01T01:00:00Z", 60, app="Editor")
    result = flow.compute_daily([*malformed,good],
        [event("2026-10-01T01:00:00Z",60,status="not-afk")],tz=ZoneInfo("UTC"))
    assert result["2026-10-01"]["observed_window_seconds"] == 60


@pytest.mark.parametrize("text", [
    "I/FlowShieldExperiment: records=1000,10,0,0PRIVATE",
    "I/FlowShieldExperiment: records=1000,10,0,0,,2000,20,0,0",
    "1000,,10,0,0", "records=1000,10,0,-1",
])
def test_corrupt_intervention_records_are_not_valid_prefixes(text):
    with pytest.raises(ValueError):
        intervention.parse_loop_records(text)
