#!/usr/bin/env python3
"""Preview explicit Loop check-ins alongside local ActivityWatch aggregates.

Offline research tooling, not a NOOP importer or bidirectional sync service.
Source stores, reminder schedules, and answers are never modified. See the
companion Markdown contract for provenance and deliberately unsupported inputs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from scripts import research_anki_outcomes as anki
except ImportError:  # Direct script execution from scripts/.
    import research_anki_outcomes as anki

SCHEMA = "loop-noop-preview.v1"
SCHEMA_WITH_LEARNING = "loop-noop-preview.v2"
MAPPING_SCHEMA = "loop-noop-preview.mapping.v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 20_000
MAX_DAYS = 3660
STATES = frozenset({"YES_MANUAL", "YES_AUTO", "NO", "SKIP", "UNKNOWN"})
# Only these exported Boolean states represent an explicit answer. YES_AUTO is
# schedule satisfaction, not completion; SKIP/UNKNOWN/unlogged remain distinct.
ANSWERS = {"YES_MANUAL": True, "NO": False}
METRICS = (
    "active_seconds", "observed_window_seconds", "window_coverage_of_active",
    "context_switch_count", "fragmentation_simpson", "sustained_context_seconds",
    "median_context_dwell_seconds", "median_return_to_context_seconds",
)
MAPPING_KEYS = frozenset({
    "schema", "consent", "source_instance", "habit_key", "habit_type",
    "noop_factor_key", "timezone", "wake_day_offset", "value_encoding",
})


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parse_day(value: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("expected a calendar date in YYYY-MM-DD format")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("invalid calendar date") from None


def validate_mapping(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != MAPPING_KEYS:
        raise ValueError("mapping fields do not match the documented v1 contract")
    if raw["schema"] != MAPPING_SCHEMA or raw["consent"] != "local-preview-only":
        raise ValueError("explicit local-preview-only consent and v1 schema are required")
    if raw["habit_type"] != "boolean" or raw["value_encoding"] != "loop-named-v1":
        raise ValueError("only explicitly selected Boolean, named-state Loop exports are supported")
    for key in ("source_instance", "habit_key"):
        if not isinstance(raw[key], str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", raw[key]):
            raise ValueError("source and habit identifiers must be short opaque aliases")
    factor = raw["noop_factor_key"]
    if (not isinstance(factor, str) or not factor.strip() or len(factor) > 512
            or any(ord(c) < 32 for c in factor)):
        raise ValueError("an explicit existing NOOP factor key is required")
    if type(raw["wake_day_offset"]) is not int or raw["wake_day_offset"] not in (0, 1):
        raise ValueError("wake_day_offset must be the explicitly selected integer 0 or 1")
    if not isinstance(raw["timezone"], str):
        raise ValueError("mapping must select an IANA timezone")
    try:
        ZoneInfo(raw["timezone"])
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("mapping must select a valid IANA timezone") from None
    return dict(raw)


def parse_checkmarks(data: bytes) -> tuple[dict[str, str], int]:
    """Read one per-habit Date,Value,Notes CSV; never return notes or file paths."""
    if len(data) > MAX_BYTES:
        raise ValueError("CSV exceeds the research input-size limit")
    try:
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
        if next(reader, None) != ["Date", "Value", "Notes"]:
            raise ValueError("select one per-habit Date,Value,Notes Checkmarks.csv, not a combined export")
        states: dict[str, str] = {}
        duplicates = 0
        for index, row in enumerate(reader, 1):
            if index > MAX_ROWS:
                raise ValueError("CSV exceeds the research row limit")
            if not row:
                continue
            if len(row) != 3:
                raise ValueError(f"malformed CSV record {index}")
            day = parse_day(row[0].strip()).isoformat()
            state = row[1].strip() or "UNKNOWN"
            if state not in STATES:
                raise ValueError(f"unsupported or numeric state in CSV record {index}")
            if day in states:
                if states[day] != state:
                    raise ValueError(f"conflicting duplicate date in CSV record {index}")
                duplicates += 1
            else:
                states[day] = state
        return states, duplicates
    except (UnicodeDecodeError, csv.Error):
        raise ValueError("invalid UTF-8 or CSV encoding") from None


def _activity_daily(report: Any, timezone_name: str) -> dict[str, dict[str, Any]]:
    if report is None:
        return {}
    if not isinstance(report, dict) or report.get("schema") != "activitywatch.flow-proxies.v0":
        raise ValueError("expected the existing ActivityWatch flow-proxy report")
    source = report.get("source")
    if (not isinstance(source, dict) or source.get("timezone") != timezone_name
            or source.get("day_attribution") != "local-midnight-split-v1"):
        raise ValueError("regenerate the ActivityWatch report with matching timezone and midnight splitting")
    daily = report.get("daily")
    if not isinstance(daily, dict) or len(daily) > MAX_DAYS:
        raise ValueError("invalid ActivityWatch daily summary")
    sanitized = {}
    for day, raw in daily.items():
        parse_day(day)
        if not isinstance(raw, dict):
            raise ValueError("invalid ActivityWatch metric record")
        metrics = {}
        for key in METRICS:
            value = raw.get(key)
            if value is not None:
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError("ActivityWatch metrics must be finite nonnegative numbers or null")
                if key in ("window_coverage_of_active", "fragmentation_simpson") and value > 1:
                    raise ValueError("ActivityWatch fraction is out of range")
                if key == "context_switch_count" and value != int(value):
                    raise ValueError("ActivityWatch context switch count is not an integer")
            metrics[key] = value
        observed = metrics["observed_window_seconds"]
        active = metrics["active_seconds"]
        if observed is not None and active is not None and observed > active + 0.001:
            raise ValueError("observed window duration exceeds active duration")
        if active is not None and active > 26 * 3600:
            raise ValueError("ActivityWatch daily duration is out of range")
        # A watcher gap must never become a zero-switch/zero-fragmentation result.
        observed_day = observed is not None and observed > 0
        if not observed_day:
            for key in METRICS[3:]:
                metrics[key] = None
        sanitized[day] = {"status": "observed" if observed_day else "not_observed", **metrics}
    return sanitized


def build_preview(
    csv_data: bytes, mapping: Any, from_day: str, through_day: str,
    activity_report: Any = None, anki_report: Any = None,
) -> dict[str, Any]:
    mapping = validate_mapping(mapping)
    first, last = parse_day(from_day), parse_day(through_day)
    count = (last-first).days + 1
    if not 1 <= count <= MAX_DAYS:
        raise ValueError("preview range must contain between 1 and 3660 calendar days")
    try:
        last + timedelta(days=mapping["wake_day_offset"])
    except OverflowError:
        raise ValueError("wake-day mapping exceeds the calendar range") from None
    states, duplicates = parse_checkmarks(csv_data)
    activity = _activity_daily(activity_report, mapping["timezone"])
    learning, learning_provenance = ({}, {}) if anki_report is None else anki.daily_for_bridge(
        anki_report, mapping["timezone"],
    )
    rows = []
    for offset in range(count):
        day = first + timedelta(days=offset)
        local_day = day.isoformat()
        state = states.get(local_day, "UNLOGGED")
        identity = [mapping["source_instance"], mapping["habit_key"], local_day]
        row = {
            "observation_id": _digest(identity),
            "revision_id": _digest([identity, state, mapping]),
            "source_local_day": local_day,
            "outcome_wake_day": (day + timedelta(days=mapping["wake_day_offset"])).isoformat(),
            "event_timestamp_utc": None,  # CSV has dates, not observed instants.
            "source_state": state,
            "explicit_journal_answer_preview": ANSWERS.get(state),
            "activity_on_source_day": activity.get(local_day),
        }
        if anki_report is not None:
            row["learning_on_source_day"] = learning.get(local_day)
        rows.append(row)
    counts = Counter(row["source_state"] for row in rows)
    result = {
        "schema": SCHEMA if anki_report is None else SCHEMA_WITH_LEARNING,
        "mode": "local-preview-only",
        "noop_write_performed": False,
        "target_catalog_verified": False,
        "mapping": mapping,
        "provenance": {
            "csv_sha256": hashlib.sha256(csv_data).hexdigest(),
            "mapping_sha256": _digest(mapping),
            "timestamp_precision": "civil_day_only",
            "loop_entries": "computed_export_not_raw_entry_history",
            "activity_join": "source_local_day_not_outcome_wake_day",
            "target": "proposal_only_not_a_NOOP_import_format",
        },
        "privacy": {"notes_emitted": False, "raw_context_names_emitted": False},
        "summary": {"days": count, "identical_duplicate_rows": duplicates,
                    "source_state_counts": dict(sorted(counts.items()))},
        "observations": rows,
    }

    if anki_report is not None:
        result["provenance"]["learning_report"] = learning_provenance
        result["privacy"]["card_contents_emitted"] = False
        result["privacy"]["card_ids_emitted"] = False
    return result


def _read_bounded(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES+1)
    if len(data) > MAX_BYTES:
        raise ValueError("input file exceeds the research size limit")
    return data


def _load_json(data: bytes) -> Any:
    def constant(_: str) -> None:
        raise ValueError("non-finite JSON constants are not accepted")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate JSON object key")
            out[key] = value
        return out

    try:
        return json.loads(data.decode("utf-8-sig"), parse_constant=constant, object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("invalid UTF-8 JSON input") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("checkmarks", type=Path, help="one per-habit Checkmarks.csv")
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--from-day", required=True)
    parser.add_argument("--through-day", required=True)
    parser.add_argument("--activity-report", type=Path)
    parser.add_argument("--anki-report", type=Path, help="optional sanitized Anki review-summary v1 JSON")
    parser.add_argument("--output", type=Path, help="new JSON file; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        sources = [args.checkmarks, args.mapping]
        if args.activity_report:
            sources.append(args.activity_report)
        if args.anki_report:
            sources.append(args.anki_report)
        if args.output and args.output.resolve() in {p.resolve() for p in sources}:
            raise ValueError("output must not replace an input file")
        report = build_preview(
            _read_bounded(args.checkmarks), _load_json(_read_bounded(args.mapping)),
            args.from_day, args.through_day,
            _load_json(_read_bounded(args.activity_report)) if args.activity_report else None,
            _load_json(_read_bounded(args.anki_report)) if args.anki_report else None,
        )
        rendered = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+"\n"
        if args.output:
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as out:
                out.write(rendered)
        else:
            print(rendered, end="")
        return 0
    except FileExistsError:
        parser.exit(2, "error: output already exists; select a new path\n")
    except OSError:
        parser.exit(2, "error: input/output file access failed\n")
    except (ValueError, TypeError, OverflowError):
        # Deliberately exclude exception strings and input values from CLI logs.
        parser.exit(2, "error: invalid input or mapping; check the documented v1 contract\n")

    # argparse exits in production; retain an explicit integer return for test doubles.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
