from datetime import datetime, timedelta, timezone

import scripts.research_flow_metrics as flow


def _event(start: datetime, seconds: float, data: dict) -> dict:
    return {
        "timestamp": start.isoformat(),
        "duration": seconds,
        "data": data,
    }


def test_focus_proxies_clip_to_active_and_measure_fragmentation() -> None:
    start = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)
    afk = [_event(start, 3600, {"status": "not-afk"})]
    window = [
        _event(start, 25 * 60, {"app": "Editor", "title": "ignored secret"}),
        _event(start + timedelta(minutes=25), 5 * 60, {"app": "Slack", "title": "ignored"}),
        _event(start + timedelta(minutes=30), 20 * 60, {"app": "Editor"}),
        _event(start + timedelta(minutes=50), 10 * 60, {"app": "Browser", "url": "https://private"}),
    ]

    metrics = flow.compute_metrics(window, afk)

    assert metrics["active_seconds"] == 3600
    assert metrics["observed_window_seconds"] == 3600
    assert metrics["window_coverage_of_active"] == 1.0
    assert metrics["context_switch_count"] == 3
    assert metrics["switches_per_active_hour"] == 3.0
    assert metrics["fragmentation_simpson"] == 0.402778
    assert metrics["sustained_context_block_count"] == 2
    assert metrics["longest_sustained_context_seconds"] == 1500
    assert metrics["return_to_context_episode_count"] == 1
    assert metrics["median_return_to_context_seconds"] == 300
    assert metrics["short_diversion_return_count"] == 1


def test_window_time_outside_not_afk_is_excluded() -> None:
    start = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)
    afk = [
        _event(start, 10 * 60, {"status": "not-afk"}),
        _event(start + timedelta(minutes=10), 10 * 60, {"status": "afk"}),
    ]
    window = [_event(start, 20 * 60, {"app": "Editor"})]

    metrics = flow.compute_metrics(window, afk)

    assert metrics["active_seconds"] == 600
    assert metrics["observed_window_seconds"] == 600
    assert metrics["context_switch_count"] == 0
    assert metrics["sustained_context_block_count"] == 0


def test_user_context_groups_turn_tool_switches_into_one_work_context() -> None:
    start = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)
    afk = [_event(start, 30 * 60, {"status": "not-afk"})]
    window = [
        _event(start, 10 * 60, {"app": "Code"}),
        _event(start + timedelta(minutes=10), 5 * 60, {"app": "Terminal"}),
        _event(start + timedelta(minutes=15), 15 * 60, {"app": "Code"}),
    ]

    raw = flow.compute_metrics(window, afk)
    grouped = flow.compute_metrics(
        window,
        afk,
        context_map={"Code": "coding", "Terminal": "coding"},
    )

    assert raw["context_switch_count"] == 2
    assert grouped["context_switch_count"] == 0
    assert grouped["fragmentation_simpson"] == 0.0
    assert grouped["sustained_context_block_count"] == 1
    assert grouped["longest_sustained_context_seconds"] == 1800


def test_return_latency_does_not_cross_afk_session_boundary() -> None:
    start = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)
    afk = [
        _event(start, 10 * 60, {"status": "not-afk"}),
        _event(start + timedelta(minutes=20), 10 * 60, {"status": "not-afk"}),
    ]
    window = [
        _event(start, 5 * 60, {"app": "Editor"}),
        _event(start + timedelta(minutes=5), 5 * 60, {"app": "Mail"}),
        _event(start + timedelta(minutes=20), 10 * 60, {"app": "Editor"}),
    ]

    metrics = flow.compute_metrics(window, afk)
    assert metrics["return_to_context_episode_count"] == 0


def test_titles_urls_and_content_do_not_affect_metrics() -> None:
    start = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)
    afk = [_event(start, 1200, {"status": "not-afk"})]
    left = [
        _event(
            start,
            1200,
            {
                "app": "Browser",
                "title": "Bank account 1234",
                "url": "https://example.test/?token=secret",
            },
        )
    ]
    right = [
        _event(
            start,
            1200,
            {
                "app": "Browser",
                "title": "Completely different",
                "url": "https://other.invalid/private",
                "extra": "sensitive text",
            },
        )
    ]

    assert flow.compute_metrics(left, afk) == flow.compute_metrics(right, afk)


def test_export_bucket_selection_requires_hostname_when_ambiguous() -> None:
    buckets = {
        "w-a": {"type": "currentwindow", "hostname": "a", "events": []},
        "w-b": {"type": "currentwindow", "hostname": "b", "events": []},
    }

    try:
        flow._select_bucket(buckets, "currentwindow", None)
    except ValueError as exc:
        assert "pass --hostname" in str(exc)
    else:
        raise AssertionError("expected ambiguous bucket selection to fail")

    bucket_id, _ = flow._select_bucket(buckets, "currentwindow", "b")
    assert bucket_id == "w-b"
