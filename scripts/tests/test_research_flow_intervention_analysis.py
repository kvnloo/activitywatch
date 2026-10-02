from datetime import datetime, timedelta, timezone

from scripts import research_flow_intervention_analysis as analysis


def _event(start: datetime, seconds: float, data: dict) -> dict:
    return {
        "timestamp": start.isoformat(),
        "duration": seconds,
        "data": data,
    }


def test_parse_loop_records_from_logcat_or_raw_csv() -> None:
    raw = "1000,10,0,0,2000,20,1520,1"
    parsed = analysis.parse_loop_records(raw)
    assert parsed == [
        {
            "observed_epoch_ms": 1000,
            "reminder_time": 10,
            "deferred_until": 0,
            "shielded": False,
        },
        {
            "observed_epoch_ms": 2000,
            "reminder_time": 20,
            "deferred_until": 1520,
            "shielded": True,
        },
    ]

    log = (
        "I/FlowShieldExperiment: focus_shield=report until=0 reminders=2 "
        "deferrals=1 records=" + raw
    )
    assert analysis.parse_loop_records(log) == parsed


def test_event_aligned_analysis_distinguishes_boundary_switch_from_shield() -> None:
    start = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)
    control_anchor = start + timedelta(minutes=10)
    shield_anchor = start + timedelta(minutes=70)

    afk = [_event(start, 2 * 60 * 60, {"status": "not-afk"})]
    window = [
        # Control: reminder boundary coincides with Editor -> Slack switch.
        _event(start, 10 * 60, {"app": "Editor"}),
        _event(control_anchor, 2 * 60, {"app": "Slack"}),
        _event(control_anchor + timedelta(minutes=2), 28 * 60, {"app": "Editor"}),
        # Shield: uninterrupted Editor context through reminder boundary.
        _event(start + timedelta(minutes=60), 40 * 60, {"app": "Editor"}),
    ]

    control = analysis.analyze_record(
        {
            "observed_epoch_ms": int(control_anchor.timestamp() * 1000),
            "reminder_time": 1_000,
            "deferred_until": 0,
            "shielded": False,
        },
        window,
        afk,
        {},
    )
    shield = analysis.analyze_record(
        {
            "observed_epoch_ms": int(shield_anchor.timestamp() * 1000),
            "reminder_time": 2_000,
            "deferred_until": 2_000 + 25 * 60 * 1000,
            "shielded": True,
        },
        window,
        afk,
        {},
    )

    assert control["condition"] == "control"
    assert control["boundary_context_covered"] is True
    assert control["same_context_across_boundary"] is False
    assert control["switched_within_2m"] is True

    assert shield["condition"] == "shield"
    assert shield["boundary_context_covered"] is True
    assert shield["same_context_across_boundary"] is True
    assert shield["switched_within_2m"] is False
    assert shield["defer_delay_seconds"] == 1500.0

    summary = analysis.summarize([control, shield])
    assert summary["control"]["n"] == 1
    assert summary["shield"]["n"] == 1
    assert summary["control"]["switch_within_2m_rate"] == 1.0
    assert summary["shield"]["switch_within_2m_rate"] == 0.0


def test_clipping_preserves_only_requested_window() -> None:
    start = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)
    event = _event(start, 600, {"app": "Editor", "title": "private"})
    clipped = analysis.clip_events(
        [event],
        start + timedelta(minutes=2),
        start + timedelta(minutes=4),
    )
    assert len(clipped) == 1
    assert clipped[0]["duration"] == 120
    assert clipped[0]["data"]["title"] == "private"
