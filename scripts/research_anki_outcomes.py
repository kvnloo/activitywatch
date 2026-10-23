#!/usr/bin/env python3
"""Summarize a user-exported Anki revlog CSV without reading a live collection.

Only daily counts and answer-button aggregates leave this process. This is not
Anki True Retention, a delayed-recall experiment, or an FSRS scheduler. Source
semantics and privacy limits are documented in research_anki_outcomes.md.
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
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA = "anki-review-summary.v1"
DAY_ATTRIBUTION = "local-midnight-v1"
MAX_BYTES = 32 * 1024 * 1024
MAX_ROWS = 200_000
MAX_DAYS = 3660
UINT32_MAX = 2**32 - 1
HEADER = ("id", "cid", "usn", "ease", "ivl", "lastIvl", "factor", "time", "type")
KINDS = ("learning", "review", "relearning", "filtered")
# Retain button numbers: legacy V1 learning used 3 for Easy, not Good.
BUTTONS = ("1", "2", "3", "4")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _day(value: Any) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("invalid calendar day")
    return date.fromisoformat(value)


def _zone(name: Any) -> ZoneInfo:
    if not isinstance(name, str):
        raise ValueError("explicit IANA timezone required")
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("invalid IANA timezone") from None


def _alias(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", value):
        raise ValueError("source_instance must be a short opaque alias")
    return value


def _range(first: str, last: str) -> tuple[date, int]:
    start, end = _day(first), _day(last)
    count = (end - start).days + 1
    if not 1 <= count <= MAX_DAYS:
        raise ValueError("range must contain between 1 and 3660 days")
    return start, count


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _local_day(timestamp_ms: int, zone: tzinfo) -> str:
    try:
        return (EPOCH + timedelta(milliseconds=timestamp_ms)).astimezone(zone).date().isoformat()
    except (OverflowError, ValueError):
        raise ValueError("review timestamp is out of supported calendar range") from None


def parse_revlog(data: bytes) -> tuple[list[tuple[int, ...]], int]:
    """Accept the nine native revlog columns only. Return deduplicated numeric rows.

    Card IDs are used in memory for per-card/day deduplication, never emitted.
    A repeated review ID with different fields is ambiguous and rejected.
    """
    if len(data) > MAX_BYTES:
        raise ValueError("CSV exceeds input-size limit")
    try:
        reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
        header = next(reader, [])
        if len(header) != len(HEADER) or set(header) != set(HEADER):
            raise ValueError("expected exactly the native revlog columns")
        positions = [header.index(key) for key in HEADER]
        unique: dict[int, tuple[int, ...]] = {}
        duplicates = 0
        for index, row in enumerate(reader, 1):
            if index > MAX_ROWS:
                raise ValueError("CSV exceeds row limit")
            if not row:
                continue
            if len(row) != len(HEADER):
                raise ValueError("malformed revlog row")
            fields = [row[pos].strip() for pos in positions]
            if any(not re.fullmatch(r"-?[0-9]{1,19}", field) for field in fields):
                raise ValueError("revlog fields must be bounded integers")
            values = tuple(int(field) for field in fields)
            rid, cid, usn, ease, ivl, previous, factor, elapsed, kind = values
            if (not 0 < rid < 2**63 or not 0 < cid < 2**63
                    or not -1 <= usn < 2**31 or not 0 <= ease <= 4
                    or not -(2**31) <= ivl < 2**31 or not -(2**31) <= previous < 2**31
                    or not 0 <= factor <= UINT32_MAX or not 0 <= elapsed <= UINT32_MAX
                    or not 0 <= kind <= 5):
                raise ValueError("unsupported revlog value")
            _local_day(rid, timezone.utc)  # Validate excluded rows too; no partial evidence.
            if rid in unique:
                if unique[rid] != values:
                    raise ValueError("conflicting duplicate review ID")
                duplicates += 1
            else:
                unique[rid] = values
        return sorted(unique.values()), duplicates
    except (UnicodeDecodeError, csv.Error):
        raise ValueError("invalid UTF-8 CSV") from None


def _summarize(rows: list[tuple[int, ...]]) -> dict[str, Any]:
    # Types 4/5 and rating 0 represent non-answer operations, not learned material.
    rated = [row for row in rows if row[8] < 4 and row[3] > 0]
    kind_counts = Counter(KINDS[row[8]] for row in rated)
    button_counts = Counter(BUTTONS[row[3] - 1] for row in rated)
    first_by_card: dict[int, tuple[int, ...]] = {}
    for row in rated:  # Input is ordered by timestamp/review ID, not CSV row order.
        first_by_card.setdefault(row[1], row)
    # Only a card's first rated event on this civil day can enter this metric.
    # Learning, relearning and filtered/cram first events do NOT count as reviews.
    first_reviews = [row for row in first_by_card.values() if row[8] == 1]
    failed = sum(row[3] == 1 for row in first_reviews)
    timed = [row[7] for row in rated if row[7] > 0]
    return {
        "status": "rated_reviews_observed" if rated else "no_rated_reviews_in_export",
        "rated_events": len(rated),
        "unique_cards": len(first_by_card),
        "non_answer_events": len(rows) - len(rated),
        "by_kind": {key: kind_counts[key] for key in KINDS},
        "buttons": {key: button_counts[key] for key in BUTTONS},
        "timed_events": len(timed),
        "recorded_answer_seconds": sum(timed) / 1000 if timed else None,
        "first_scheduled_reviews": {
            "count": len(first_reviews),
            "again_count": failed,
            "pass_count": len(first_reviews) - failed,
            "rated_recall_fraction": (len(first_reviews) - failed) / len(first_reviews)
            if first_reviews else None,
        },
    }


def build_summary(
    csv_data: bytes, *, source_instance: str, timezone_name: str,
    from_day: str, through_day: str, consent: str,
) -> dict[str, Any]:
    if consent != "local-preview-only":
        raise ValueError("explicit local-preview-only consent is required")
    alias, zone = _alias(source_instance), _zone(timezone_name)
    start, count = _range(from_day, through_day)
    rows, duplicates = parse_revlog(csv_data)
    grouped: dict[str, list[tuple[int, ...]]] = defaultdict(list)
    outside = 0
    for row in rows:
        day = _local_day(row[0], zone)
        if from_day <= day <= through_day:
            grouped[day].append(row)
        else:
            outside += 1
    daily = {
        (start + timedelta(days=offset)).isoformat():
        _summarize(grouped[(start + timedelta(days=offset)).isoformat()])
        for offset in range(count)
    }
    return {
        "schema": SCHEMA,
        "mode": "local-preview-only",
        "source": {
            "source_instance": alias, "timezone": timezone_name,
            "day_attribution": DAY_ATTRIBUTION,
            "coverage": "export_only_completeness_unverified",
        },
        "range": {"from_day": from_day, "through_day": through_day},
        "provenance": {
            "csv_sha256": hashlib.sha256(csv_data).hexdigest(),
            "recipe": "answer-buttons-first-scheduled-per-civil-day-v1",
            "unique_input_rows": len(rows), "identical_duplicate_rows": duplicates,
            "outside_range_rows": outside,
        },
        "privacy": {"card_ids_emitted": False, "review_ids_emitted": False,
                    "card_contents_read": False, "deck_names_read": False},
        "limitations": [
            "self_ratings_not_objective_correctness",
            "not_Anki_True_Retention_or_24h_7d_retention",
            "local_midnight_not_Anki_scheduler_rollover",
            "export_absence_not_verified_no_study",
            "recorded_time_can_be_capped_not_session_duration",
            "FSRS_enablement_and_parameters_not_inferred",
        ],
        "daily": daily,
    }


def daily_for_bridge(report: Any, timezone_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate and allowlist a summary; never forward arbitrary imported fields."""
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA
            or report.get("mode") != "local-preview-only"):
        raise ValueError("expected a versioned local Anki summary")
    source, span = report.get("source"), report.get("range")
    if (not isinstance(source, dict) or source.get("timezone") != timezone_name
            or source.get("day_attribution") != DAY_ATTRIBUTION
            or source.get("coverage") != "export_only_completeness_unverified"
            or not isinstance(span, dict)):
        raise ValueError("Anki timezone/day attribution/coverage mismatch")
    _zone(timezone_name)
    alias = _alias(source.get("source_instance"))
    start, count = _range(span.get("from_day"), span.get("through_day"))
    daily = report.get("daily")
    if not isinstance(daily, dict) or len(daily) != count:
        raise ValueError("incomplete Anki summary range")
    provenance = report.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("Anki provenance missing")
    input_hash = provenance.get("csv_sha256")
    if not isinstance(input_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", input_hash):
        raise ValueError("Anki input hash missing")
    sanitized = {}
    for offset in range(count):
        day = (start + timedelta(days=offset)).isoformat()
        raw = daily.get(day)
        if not isinstance(raw, dict):
            raise ValueError("Anki daily summary missing")
        def number(value: Any) -> int:
            if type(value) is not int or not 0 <= value <= MAX_ROWS:
                raise ValueError("invalid Anki aggregate count")
            return value
        n, unique, excluded, timed = [number(raw.get(key)) for key in
                                    ("rated_events", "unique_cards", "non_answer_events", "timed_events")]
        by_kind, buttons, first = raw.get("by_kind"), raw.get("buttons"), raw.get("first_scheduled_reviews")
        if not all(isinstance(part, dict) for part in (by_kind, buttons, first)):
            raise ValueError("Anki aggregate groups missing")
        kinds = {key: number(by_kind.get(key)) for key in KINDS}
        ratings = {key: number(buttons.get(key)) for key in BUTTONS}
        total, again, passed = [number(first.get(key)) for key in ("count", "again_count", "pass_count")]
        expected_status = "rated_reviews_observed" if n else "no_rated_reviews_in_export"
        if (sum(kinds.values()) != n or sum(ratings.values()) != n
                or not 0 <= unique <= n or (n > 0 and unique == 0) or timed > n
                or n + excluded > MAX_ROWS or total > min(unique, kinds["review"])
                or again + passed != total or again > ratings["1"]
                or passed > n - ratings["1"] or raw.get("status") != expected_status):
            raise ValueError("inconsistent Anki aggregate counts")
        fraction = first.get("rated_recall_fraction")
        expected_fraction = passed / total if total else None
        if ((expected_fraction is None and fraction is not None)
                or (expected_fraction is not None and
                    (type(fraction) not in (int, float) or not math.isfinite(fraction)
                     or abs(fraction - expected_fraction) > 1e-12))):
            raise ValueError("inconsistent Anki rating fraction")
        seconds = raw.get("recorded_answer_seconds")
        if ((timed == 0 and seconds is not None) or (timed > 0 and
                (type(seconds) not in (int, float) or not math.isfinite(seconds)
                 or not timed / 1000 <= seconds <= timed * UINT32_MAX / 1000))):
            raise ValueError("inconsistent Anki recorded time")
        value = {
            "status": expected_status, "rated_events": n, "unique_cards": unique,
            "non_answer_events": excluded, "by_kind": kinds, "buttons": ratings,
            "timed_events": timed, "recorded_answer_seconds": seconds,
            "first_scheduled_reviews": {"count": total, "again_count": again,
                                        "pass_count": passed, "rated_recall_fraction": expected_fraction},
        }
        identity = [alias, timezone_name, DAY_ATTRIBUTION, day]
        sanitized[day] = {**value, "observation_id": _hash(identity),
                          "revision_id": _hash([identity, value])}
    return sanitized, {
        "source_instance": alias, "csv_sha256": input_hash,
        "summary_sha256": _hash(sanitized), "schema": SCHEMA,
        "day_attribution": DAY_ATTRIBUTION,
        "coverage": "export_only_completeness_unverified",
        "join": "source_local_day_not_outcome_wake_day",
        "interpretation": "self_rated_reviews_not_24h_7d_retention",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("revlog", type=Path, help="native nine-column revlog CSV exported by the user")
    parser.add_argument("--consent", required=True, choices=["local-preview-only"])
    parser.add_argument("--source-instance", required=True, help="opaque local alias, never a deck name")
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--from-day", required=True)
    parser.add_argument("--through-day", required=True)
    parser.add_argument("--output", type=Path, help="new private JSON file; never overwrite an existing path")
    args = parser.parse_args(argv)
    try:
        with args.revlog.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        report = build_summary(data, source_instance=args.source_instance, timezone_name=args.timezone,
                               from_day=args.from_day, through_day=args.through_day, consent=args.consent)
        rendered = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
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
        parser.exit(2, "error: invalid revlog input or configuration; check the documented contract\n")

    # argparse exits in production; retain an explicit integer return for test doubles.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
