#!/usr/bin/env python3
"""Join Loop focus-shield reminder events to ActivityWatch behavioral telemetry.

Input contains no habit identity. Each Loop record is:
    observedEpochMillis, reminderTime, deferredUntil, shieldedFlag

The output is event-aligned aggregate telemetry only; app/context names are never emitted.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import research_flow_metrics as flow


SCHEMA = "activitywatch.flow-shield-intervention.v0"


def parse_loop_records(text: str) -> list[dict[str, int | bool]]:
    """Parse raw comma-separated values or a logcat line containing records=..."""
    matches = re.findall(r"(?:^|\s)records=([0-9,]*)", text)
    payload = matches[-1] if matches else text.strip()
    payload = payload.strip().strip(",")
    if not payload:
        return []
    values = [int(x) for x in payload.split(",") if x.strip()]
    if len(values) % 4 != 0:
        raise ValueError(
            f"Loop focus-shield records must contain groups of 4 values; got {len(values)}"
        )
    out: list[dict[str, int | bool]] = []
    for i in range(0, len(values), 4):
        observed, reminder_time, deferred_until, shielded = values[i : i + 4]
        if shielded not in (0, 1):
            raise ValueError(f"shieldedFlag must be 0/1, got {shielded}")
        out.append(
            {
                "observed_epoch_ms": observed,
                "reminder_time": reminder_time,
                "deferred_until": deferred_until,
                "shielded": bool(shielded),
            }
        )
    return out


def _clip_event(
    event: dict[str, Any],
    start: datetime,
    end: datetime,
) -> dict[str, Any] | None:
    iv = flow._event_interval(event)
    if iv is None:
        return None
    clipped_start = max(iv.start, start)
    clipped_end = min(iv.end, end)
    if clipped_end <= clipped_start:
        return None
    return {
        "timestamp": clipped_start.isoformat(),
        "duration": (clipped_end - clipped_start).total_seconds(),
        "data": dict(event.get("data") or {}),
    }


def clip_events(
    events: list[dict[str, Any]],
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for event in events:
        clipped = _clip_event(event, start, end)
        if clipped is not None:
            out.append(clipped)
    return out


def metrics_for_window(
    window_events: list[dict[str, Any]],
    afk_events: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    context_map: dict[str, str],
) -> dict[str, Any]:
    return flow.compute_metrics(
        clip_events(window_events, start, end),
        clip_events(afk_events, start, end),
        context_map=context_map,
        # Event-aligned windows are shorter than the passive baseline's focus threshold.
        focus_min_seconds=20 * 60,
        return_horizon_seconds=30 * 60,
    )


def _context_on_each_side(
    window_events: list[dict[str, Any]],
    afk_events: list[dict[str, Any]],
    anchor: datetime,
    context_map: dict[str, str],
    probe_seconds: float = 15.0,
) -> tuple[bool, bool]:
    """Return (covered, same_context) without exposing the context identity."""
    before_start = anchor - timedelta(seconds=probe_seconds)
    after_end = anchor + timedelta(seconds=probe_seconds)
    segments = flow.clip_to_active(
        flow.window_segments(
            clip_events(window_events, before_start, after_end),
            context_map,
        ),
        flow.active_intervals(clip_events(afk_events, before_start, after_end)),
    )
    before = [s for s in segments if s.start < anchor and s.end >= before_start]
    after = [s for s in segments if s.end > anchor and s.start <= after_end]
    if not before or not after:
        return False, False
    return True, before[-1].context == after[0].context


def analyze_record(
    record: dict[str, int | bool],
    window_events: list[dict[str, Any]],
    afk_events: list[dict[str, Any]],
    context_map: dict[str, str],
) -> dict[str, Any]:
    anchor = datetime.fromtimestamp(
        int(record["observed_epoch_ms"]) / 1000.0,
        tz=timezone.utc,
    )
    pre10 = metrics_for_window(
        window_events,
        afk_events,
        anchor - timedelta(minutes=10),
        anchor,
        context_map,
    )
    post2 = metrics_for_window(
        window_events,
        afk_events,
        anchor,
        anchor + timedelta(minutes=2),
        context_map,
    )
    post10 = metrics_for_window(
        window_events,
        afk_events,
        anchor,
        anchor + timedelta(minutes=10),
        context_map,
    )
    post30 = metrics_for_window(
        window_events,
        afk_events,
        anchor,
        anchor + timedelta(minutes=30),
        context_map,
    )
    boundary_covered, same_context = _context_on_each_side(
        window_events,
        afk_events,
        anchor,
        context_map,
    )

    shielded = bool(record["shielded"])
    reminder_time = int(record["reminder_time"])
    deferred_until = int(record["deferred_until"])
    return {
        "anchor_utc": anchor.isoformat(),
        "condition": "shield" if shielded else "control",
        "defer_delay_seconds": (
            round((deferred_until - reminder_time) / 1000.0, 3)
            if shielded and deferred_until
            else 0.0
        ),
        "boundary_context_covered": boundary_covered,
        "same_context_across_boundary": same_context if boundary_covered else None,
        "switched_within_2m": (
            post2["context_switch_count"] > 0
            if post2["observed_window_seconds"] > 0
            else None
        ),
        "pre_10m": pre10,
        "post_2m": post2,
        "post_10m": post10,
        "post_30m": post30,
    }


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for condition in ("control", "shield"):
        rows = [e for e in events if e["condition"] == condition]
        switched = [e["switched_within_2m"] for e in rows if e["switched_within_2m"] is not None]
        stable = [
            e["same_context_across_boundary"]
            for e in rows
            if e["same_context_across_boundary"] is not None
        ]
        post10_switches = [
            float(e["post_10m"]["context_switch_count"])
            for e in rows
            if e["post_10m"]["observed_window_seconds"] > 0
        ]
        post30_returns = [
            float(e["post_30m"]["median_return_to_context_seconds"])
            for e in rows
            if e["post_30m"]["median_return_to_context_seconds"] is not None
        ]
        out[condition] = {
            "n": len(rows),
            "switch_within_2m_rate": (
                sum(bool(x) for x in switched) / len(switched) if switched else None
            ),
            "same_context_across_boundary_rate": (
                sum(bool(x) for x in stable) / len(stable) if stable else None
            ),
            "mean_post_10m_switches": (
                sum(post10_switches) / len(post10_switches) if post10_switches else None
            ),
            "mean_post_30m_median_return_seconds": (
                sum(post30_returns) / len(post30_returns) if post30_returns else None
            ),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path, help="ActivityWatch JSON export")
    parser.add_argument(
        "loop_records",
        type=Path,
        help="Text file containing Loop debug report or raw records CSV",
    )
    parser.add_argument("--hostname")
    parser.add_argument("--context-map", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    buckets = flow._load_export(args.export)
    _, window_bucket = flow._select_bucket(buckets, "currentwindow", args.hostname)
    _, afk_bucket = flow._select_bucket(buckets, "afkstatus", args.hostname)
    context_map = flow._load_context_map(args.context_map)
    records = parse_loop_records(args.loop_records.read_text(encoding="utf-8"))

    event_rows = [
        analyze_record(
            record,
            flow._bucket_events(window_bucket),
            flow._bucket_events(afk_bucket),
            context_map,
        )
        for record in records
    ]
    report = {
        "schema": SCHEMA,
        "privacy": {
            "loop_identity_fields_used": False,
            "raw_context_names_emitted": False,
        },
        "events": event_rows,
        "summary": summarize(event_rows),
    }

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
