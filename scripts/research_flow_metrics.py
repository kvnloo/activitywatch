#!/usr/bin/env python3
"""Compute privacy-preserving focus/fragmentation proxies from ActivityWatch export data.

This is an experiment, not a flow detector. It intentionally ignores window
titles, URLs, screenshots, OCR, keystrokes, and content. The default signal set
is only:

- event timestamp + duration,
- current-window application identity (optionally mapped into a user-defined
  context group), and
- AFK status.

The output contains aggregate metrics only; raw application names are never
written unless the caller supplies them as explicit context-group labels.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


SCHEMA = "activitywatch.flow-proxies.v0"


@dataclass(frozen=True)
class Segment:
    start: datetime
    end: datetime
    context: str

    @property
    def seconds(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())


def _parse_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _event_interval(event: dict[str, Any]) -> Interval | None:
    try:
        start = _parse_timestamp(str(event["timestamp"]))
        duration = float(event.get("duration") or 0.0)
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    return Interval(start, start + timedelta(seconds=duration))


def _bucket_type(bucket: dict[str, Any]) -> str:
    return str(bucket.get("type") or bucket.get("_type") or "")


def _bucket_events(bucket: dict[str, Any]) -> list[dict[str, Any]]:
    events = bucket.get("events")
    return [e for e in events if isinstance(e, dict)] if isinstance(events, list) else []


def _load_export(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    buckets = raw.get("buckets", raw)
    if not isinstance(buckets, dict):
        raise ValueError("ActivityWatch export must contain a buckets object")
    return {str(k): v for k, v in buckets.items() if isinstance(v, dict)}


def _select_bucket(
    buckets: dict[str, dict[str, Any]],
    expected_type: str,
    hostname: str | None,
) -> tuple[str, dict[str, Any]]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for bucket_id, bucket in buckets.items():
        if _bucket_type(bucket) != expected_type:
            continue
        if hostname is not None and str(bucket.get("hostname") or "") != hostname:
            continue
        candidates.append((bucket_id, bucket))

    if not candidates:
        suffix = f" for hostname {hostname!r}" if hostname else ""
        raise ValueError(f"no {expected_type!r} bucket found{suffix}")
    if len(candidates) > 1:
        names = ", ".join(
            f"{bucket_id}({bucket.get('hostname') or '?'})" for bucket_id, bucket in candidates
        )
        raise ValueError(
            f"multiple {expected_type!r} buckets match: {names}; pass --hostname"
        )
    return candidates[0]


def _merge_intervals(intervals: list[Interval], join_gap_seconds: float = 2.0) -> list[Interval]:
    out: list[Interval] = []
    for cur in sorted(intervals, key=lambda x: (x.start, x.end)):
        if not out:
            out.append(cur)
            continue
        prev = out[-1]
        gap = (cur.start - prev.end).total_seconds()
        if gap <= join_gap_seconds:
            out[-1] = Interval(prev.start, max(prev.end, cur.end))
        else:
            out.append(cur)
    return out


def active_intervals(afk_events: list[dict[str, Any]]) -> list[Interval]:
    active: list[Interval] = []
    for event in afk_events:
        if (event.get("data") or {}).get("status") != "not-afk":
            continue
        iv = _event_interval(event)
        if iv is not None:
            active.append(iv)
    return _merge_intervals(active)


def window_segments(
    window_events: list[dict[str, Any]],
    context_map: dict[str, str] | None = None,
) -> list[Segment]:
    context_map = context_map or {}
    out: list[Segment] = []
    for event in window_events:
        iv = _event_interval(event)
        if iv is None:
            continue
        data = event.get("data") or {}
        app = str(data.get("app") or "(unknown)")
        context = str(context_map.get(app, app))
        out.append(Segment(iv.start, iv.end, context))
    return sorted(out, key=lambda x: (x.start, x.end))


def clip_to_active(segments: list[Segment], active: list[Interval]) -> list[Segment]:
    """Intersect window segments with active intervals.

    Window/AFK watcher heartbeats are expected to form non-overlapping timelines.
    We still sort and coalesce same-context pieces after clipping.
    """
    clipped: list[Segment] = []
    i = 0
    active = sorted(active, key=lambda x: x.start)
    for seg in sorted(segments, key=lambda x: x.start):
        while i < len(active) and active[i].end <= seg.start:
            i += 1
        j = i
        while j < len(active) and active[j].start < seg.end:
            start = max(seg.start, active[j].start)
            end = min(seg.end, active[j].end)
            if end > start:
                clipped.append(Segment(start, end, seg.context))
            if active[j].end >= seg.end:
                break
            j += 1
    return coalesce_segments(clipped)


def coalesce_segments(segments: list[Segment], join_gap_seconds: float = 1.0) -> list[Segment]:
    out: list[Segment] = []
    for cur in sorted(segments, key=lambda x: (x.start, x.end)):
        if not out:
            out.append(cur)
            continue
        prev = out[-1]
        gap = (cur.start - prev.end).total_seconds()
        if cur.context == prev.context and gap <= join_gap_seconds:
            out[-1] = Segment(prev.start, max(prev.end, cur.end), prev.context)
            continue
        # Avoid double-counting malformed overlaps between different contexts.
        if cur.start < prev.end:
            cur = Segment(prev.end, cur.end, cur.context)
            if cur.end <= cur.start:
                continue
        out.append(cur)
    return out


def _segments_by_active_interval(
    segments: list[Segment], active: list[Interval]
) -> list[list[Segment]]:
    groups: list[list[Segment]] = [[] for _ in active]
    j = 0
    for seg in segments:
        while j < len(active) and active[j].end <= seg.start:
            j += 1
        if j < len(active) and seg.start < active[j].end and seg.end > active[j].start:
            groups[j].append(seg)
    return groups


def _simpson_fragmentation(segments: list[Segment]) -> float | None:
    totals: dict[str, float] = {}
    for seg in segments:
        totals[seg.context] = totals.get(seg.context, 0.0) + seg.seconds
    total = sum(totals.values())
    if total <= 0:
        return None
    return 1.0 - sum((seconds / total) ** 2 for seconds in totals.values())


def _return_latencies(
    segments: list[Segment],
    active: list[Interval],
    horizon_seconds: float,
) -> list[float]:
    latencies: list[float] = []
    for group in _segments_by_active_interval(segments, active):
        for i in range(len(group) - 1):
            left = group[i]
            if group[i + 1].context == left.context:
                continue
            deadline = left.end.timestamp() + horizon_seconds
            for j in range(i + 1, len(group)):
                candidate = group[j]
                if candidate.start.timestamp() > deadline:
                    break
                if candidate.context == left.context:
                    latencies.append((candidate.start - left.end).total_seconds())
                    break
    return latencies


def _switch_count(segments: list[Segment], active: list[Interval]) -> int:
    total = 0
    for group in _segments_by_active_interval(segments, active):
        for prev, cur in zip(group, group[1:]):
            if prev.context != cur.context:
                total += 1
    return total


def _sustained_blocks(segments: list[Segment], minimum_seconds: float) -> list[Segment]:
    return [seg for seg in segments if seg.seconds >= minimum_seconds]


def compute_metrics(
    window_events: list[dict[str, Any]],
    afk_events: list[dict[str, Any]],
    *,
    context_map: dict[str, str] | None = None,
    focus_min_seconds: float = 20 * 60,
    return_horizon_seconds: float = 30 * 60,
) -> dict[str, Any]:
    active = active_intervals(afk_events)
    segments = clip_to_active(window_segments(window_events, context_map), active)

    active_seconds = sum(iv.seconds for iv in active)
    observed_seconds = sum(seg.seconds for seg in segments)
    switches = _switch_count(segments, active)
    dwell = [seg.seconds for seg in segments]
    sustained = _sustained_blocks(segments, focus_min_seconds)
    returns = _return_latencies(segments, active, return_horizon_seconds)
    short_returns = [x for x in returns if x <= 10 * 60]

    return {
        "active_seconds": round(active_seconds, 3),
        "observed_window_seconds": round(observed_seconds, 3),
        "window_coverage_of_active": (
            round(min(1.0, observed_seconds / active_seconds), 6)
            if active_seconds > 0
            else None
        ),
        "context_segment_count": len(segments),
        "context_switch_count": switches,
        "switches_per_active_hour": (
            round(switches / (active_seconds / 3600.0), 6)
            if active_seconds > 0
            else None
        ),
        "fragmentation_simpson": (
            round(value, 6)
            if (value := _simpson_fragmentation(segments)) is not None
            else None
        ),
        "median_context_dwell_seconds": (
            round(statistics.median(dwell), 3) if dwell else None
        ),
        "sustained_context_block_count": len(sustained),
        "sustained_context_seconds": round(sum(seg.seconds for seg in sustained), 3),
        "longest_sustained_context_seconds": (
            round(max((seg.seconds for seg in sustained), default=0.0), 3)
        ),
        "return_to_context_episode_count": len(returns),
        "median_return_to_context_seconds": (
            round(statistics.median(returns), 3) if returns else None
        ),
        "short_diversion_return_count": len(short_returns),
        "focus_min_seconds": focus_min_seconds,
        "return_horizon_seconds": return_horizon_seconds,
    }


def compute_daily(
    window_events: list[dict[str, Any]],
    afk_events: list[dict[str, Any]],
    *,
    tz: ZoneInfo,
    context_map: dict[str, str] | None = None,
    focus_min_seconds: float = 20 * 60,
    return_horizon_seconds: float = 30 * 60,
) -> dict[str, dict[str, Any]]:
    """Compute daily metrics by assigning each event to its local start date.

    This is intentionally simple for v0. Midnight-spanning events are rare and
    remain assigned to the day on which they started; a later experiment can
    split at local-day boundaries if that matters empirically.
    """
    days: set[str] = set()
    for event in [*window_events, *afk_events]:
        try:
            day = _parse_timestamp(str(event["timestamp"])).astimezone(tz).date().isoformat()
            days.add(day)
        except (KeyError, TypeError, ValueError):
            continue

    out: dict[str, dict[str, Any]] = {}
    for day in sorted(days):
        w = [
            e
            for e in window_events
            if _parse_timestamp(str(e["timestamp"])).astimezone(tz).date().isoformat() == day
        ]
        a = [
            e
            for e in afk_events
            if _parse_timestamp(str(e["timestamp"])).astimezone(tz).date().isoformat() == day
        ]
        out[day] = compute_metrics(
            w,
            a,
            context_map=context_map,
            focus_min_seconds=focus_min_seconds,
            return_horizon_seconds=return_horizon_seconds,
        )
    return out


def _load_context_map(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in raw.items()
    ):
        raise ValueError("context map must be a JSON object of app -> context strings")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export", type=Path, help="ActivityWatch JSON export")
    parser.add_argument(
        "--hostname",
        help="Select a hostname when the export contains more than one window/AFK pair",
    )
    parser.add_argument(
        "--context-map",
        type=Path,
        help="Optional JSON object mapping application names to user-defined task contexts",
    )
    parser.add_argument("--timezone", default="UTC", help="IANA timezone for daily summaries")
    parser.add_argument(
        "--focus-min-minutes",
        type=float,
        default=20.0,
        help="Minimum uninterrupted context duration counted as sustained (default: 20)",
    )
    parser.add_argument(
        "--return-horizon-minutes",
        type=float,
        default=30.0,
        help="Maximum time to count a return-to-context episode (default: 30)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write JSON report to this file instead of stdout",
    )
    args = parser.parse_args()

    buckets = _load_export(args.export)
    window_id, window_bucket = _select_bucket(buckets, "currentwindow", args.hostname)
    afk_id, afk_bucket = _select_bucket(buckets, "afkstatus", args.hostname)
    context_map = _load_context_map(args.context_map)
    tz = ZoneInfo(args.timezone)

    window = _bucket_events(window_bucket)
    afk = _bucket_events(afk_bucket)
    metrics = compute_metrics(
        window,
        afk,
        context_map=context_map,
        focus_min_seconds=args.focus_min_minutes * 60,
        return_horizon_seconds=args.return_horizon_minutes * 60,
    )
    report = {
        "schema": SCHEMA,
        "source": {
            "window_bucket": window_id,
            "afk_bucket": afk_id,
            "timezone": args.timezone,
        },
        "privacy": {
            "uses": ["timestamp", "duration", "application/context identity", "AFK status"],
            "ignores": ["window title", "URL", "screenshots", "OCR", "keystrokes", "content"],
            "raw_context_names_emitted": False,
        },
        "interpretation": {
            "claim": "behavioral proxies only; not a direct measure or diagnosis of flow",
            "sustained_context_block": (
                "continuous active time in one app/context group above the configured threshold"
            ),
            "return_to_context": (
                "time from leaving a context until first return within the configured horizon"
            ),
        },
        "overall": metrics,
        "daily": compute_daily(
            window,
            afk,
            tz=tz,
            context_map=context_map,
            focus_min_seconds=args.focus_min_minutes * 60,
            return_horizon_seconds=args.return_horizon_minutes * 60,
        ),
    }

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
