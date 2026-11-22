"""Synthetic revlog contracts only. Never open a real Anki collection or network."""
from __future__ import annotations

import csv
import io
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

from scripts import research_anki_outcomes as anki
from scripts import research_loop_bridge as bridge

ROOT = Path(__file__).resolve().parents[2]
DAY = "2026-10-19"


def millis(iso: str) -> int:
    value = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return int((value - anki.EPOCH).total_seconds() * 1000)


def row(iso="2026-10-19T18:00:00Z", cid=123, ease=3, kind=1, elapsed=2000, **kwargs):
    result = dict(zip(anki.HEADER, (millis(iso), cid, -1, ease, 7, 1, 2500, elapsed, kind)))
    return {**result, **kwargs}


def export(rows, header=anki.HEADER) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(header)
    for item in rows:
        writer.writerow(item[key] for key in header)
    return stream.getvalue().encode()


def summary(rows=(), *, data=None, **kwargs):
    return anki.build_summary(
        export(rows) if data is None else data,
        **{**dict(source_instance="anki-local", timezone_name="America/Chicago",
                  from_day=DAY, through_day=DAY, consent="local-preview-only"), **kwargs},
    )


def mapping():
    return dict(schema=bridge.MAPPING_SCHEMA, consent="local-preview-only",
                source_instance="loop-local", habit_key="habit-1", habit_type="boolean",
                noop_factor_key="Did you read before bed?", timezone="America/Chicago",
                wake_day_offset=1, value_encoding="loop-named-v1")


def preview(report=None):
    return bridge.build_preview(b"Date,Value,Notes\n2026-10-19,YES_MANUAL,private note\n",
                                mapping(), DAY, "2026-10-20", anki_report=report)


def test_native_column_order_bom_and_reordered_header():
    original = row()
    normal = anki.parse_revlog(export([original]))
    reordered = anki.parse_revlog(b"\xef\xbb\xbf" + export([original], tuple(reversed(anki.HEADER))))
    assert normal == reordered
    assert normal == ([tuple(original[key] for key in anki.HEADER)], 0)


def test_self_ratings_not_fsrs_predictions_or_objective_accuracy():
    result = summary([row()])
    daily = result["daily"][DAY]
    assert daily["rated_events"] == 1
    assert daily["buttons"] == {"1": 0, "2": 0, "3": 1, "4": 0}
    assert daily["first_scheduled_reviews"] == dict(count=1, again_count=0, pass_count=1, rated_recall_fraction=1.0)
    assert "FSRS_enablement_and_parameters_not_inferred" in result["limitations"]
    assert "not_Anki_True_Retention_or_24h_7d_retention" in result["limitations"]
    assert result["source"]["coverage"] == "export_only_completeness_unverified"


@pytest.mark.parametrize("kind", range(4))
@pytest.mark.parametrize("ease", range(1, 5))
def test_buttons_and_review_kinds_are_kept_separate(kind, ease):
    daily = summary([row(ease=ease, kind=kind)])["daily"][DAY]
    assert daily["by_kind"][anki.KINDS[kind]] == 1
    assert daily["buttons"][anki.BUTTONS[ease - 1]] == 1
    assert daily["first_scheduled_reviews"]["count"] == (1 if kind == 1 else 0)
    expected = (0.0 if ease == 1 else 1.0) if kind == 1 else None
    assert daily["first_scheduled_reviews"]["rated_recall_fraction"] == expected


@pytest.mark.parametrize("kind,ease", [(4, 0), (5, 0), (4, 3), (5, 4), (1, 0), (3, 0)])
def test_manual_reschedule_and_unrated_events_never_count_as_learning(kind, ease):
    daily = summary([row(kind=kind, ease=ease)])["daily"][DAY]
    assert daily["rated_events"] == daily["unique_cards"] == 0
    assert daily["non_answer_events"] == 1
    assert daily["status"] == "no_rated_reviews_in_export"
    assert daily["first_scheduled_reviews"]["rated_recall_fraction"] is None
    assert daily["recorded_answer_seconds"] is None


def test_same_day_failure_then_success_remains_first_review_failure():
    earlier = row(ease=1)
    later = row("2026-10-19T19:00:00Z", ease=3)
    daily = summary([later, earlier, later])["daily"][DAY]
    assert daily["rated_events"] == 2
    assert daily["unique_cards"] == 1
    assert daily["first_scheduled_reviews"] == dict(count=1, again_count=1, pass_count=0, rated_recall_fraction=0.0)


@pytest.mark.parametrize("first_kind", [0, 2, 3])
def test_learning_relearning_or_filtered_before_review_excluded_from_first_metric(first_kind):
    rows = [row(kind=first_kind), row("2026-10-19T19:00:00Z", kind=1)]
    daily = summary(rows)["daily"][DAY]
    assert daily["rated_events"] == 2
    assert daily["first_scheduled_reviews"]["count"] == 0
    assert daily["first_scheduled_reviews"]["rated_recall_fraction"] is None


def test_prior_manual_event_does_not_hide_a_real_first_rating():
    rows = [row(kind=4, ease=0), row("2026-10-19T19:00:00Z", ease=2)]
    daily = summary(rows)["daily"][DAY]
    assert daily["first_scheduled_reviews"]["rated_recall_fraction"] == 1.0


def test_unknown_timing_is_null_not_zero_and_positive_times_are_counted():
    assert summary([row(elapsed=0)])["daily"][DAY]["recorded_answer_seconds"] is None
    rows = [row(elapsed=0), row("2026-10-19T19:00:00Z", elapsed=1500)]
    daily = summary(rows)["daily"][DAY]
    assert daily["recorded_answer_seconds"] == 1.5
    assert daily["timed_events"] == 1


def test_unobserved_days_are_not_fabricated_failures_or_proof_of_no_study():
    result = summary([], through_day="2026-10-20")
    assert len(result["daily"]) == 2
    for daily in result["daily"].values():
        assert daily["status"] == "no_rated_reviews_in_export"
        assert daily["first_scheduled_reviews"]["rated_recall_fraction"] is None
    assert "export_absence_not_verified_no_study" in result["limitations"]


@pytest.mark.parametrize("instants,first,last,expected", [
    (["2026-03-08T07:59:59Z", "2026-03-08T08:00:00Z"], "2026-03-08", "2026-03-08", [2]),
    (["2026-11-01T06:30:00Z", "2026-11-01T07:30:00Z"], "2026-11-01", "2026-11-01", [2]),
    (["2027-01-01T05:59:59Z", "2027-01-01T06:00:00Z"], "2026-12-31", "2027-01-01", [1, 1]),
    (["2028-02-29T05:59:59Z", "2028-02-29T06:00:00Z"], "2028-02-28", "2028-02-29", [1, 1]),
])
def test_real_utc_instants_map_to_local_midnight_not_fixed_24h_or_scheduler_days(instants, first, last, expected):
    result = summary([row(t, cid=index + 1) for index, t in enumerate(instants)], from_day=first, through_day=last)
    assert [d["rated_events"] for d in result["daily"].values()] == expected
    assert result["source"]["day_attribution"] == anki.DAY_ATTRIBUTION


def test_timestamp_ms_is_not_seconds_and_records_outside_range_are_audited():
    rows = [row(id=millis("2026-10-19T18:00:00Z") // 1000), row()]
    result = summary(rows)
    assert result["daily"][DAY]["rated_events"] == 1
    assert result["provenance"]["outside_range_rows"] == 1


def test_duplicate_ids_stable_aggregates_and_conflicts_fail_closed():
    one = row()
    assert anki.parse_revlog(export([one, one]))[1] == 1
    assert summary([one, one])["daily"] == summary([one])["daily"]
    with pytest.raises(ValueError):
        summary([one, {**one, "ease": 1}])


@pytest.mark.parametrize("field,value", [
    ("id", "NaN"), ("id", "123garbage"), ("id", 0), ("id", 2**63),
    ("id", 2**63 - 1), ("cid", 0), ("cid", -1), ("usn", -2),
    ("ease", 5), ("ease", -1), ("ease", "3.0"), ("ease", "٣"),
    ("ivl", 2**31), ("lastIvl", -(2**31) - 1), ("factor", -1),
    ("time", -1), ("time", 2**32), ("type", 6), ("type", -1),
])
def test_bad_numeric_values_fail_closed_without_partial_metrics(field, value):
    with pytest.raises(ValueError):
        summary([row(), row("2026-10-19T19:00:00Z", **{field: value})])


@pytest.mark.parametrize("data", [
    b"", b"id,cid\n1,2\n", b"Date,Value,Notes\n2026-10-19,YES_MANUAL,private\n",
    b"id,cid,usn,ease,ivl,lastIvl,factor,time,type,notes\n",
    b"id,cid,usn,ease,ivl,lastIvl,factor,time,time\n",
    b"id,cid,usn,ease,ivl,lastIvl,factor,time,type\n1,2,3\n",
    b"id,cid,usn,ease,ivl,lastIvl,factor,time,type\n\"unclosed\n", b"\xff\xfe",
])
def test_non_revlog_exports_and_malformed_csv_rejected(data):
    with pytest.raises(ValueError):
        summary(data=data)


def test_negative_interval_seconds_supported_but_not_misread_as_retention():
    result = summary([row(ivl=-600, lastIvl=-60)])
    assert result["daily"][DAY]["rated_events"] == 1
    assert "lastIvl" not in json.dumps(result)


@pytest.mark.parametrize("kwargs", [
    {"consent": "auto-sync"}, {"source_instance": "private deck name"},
    {"source_instance": "x" * 65}, {"timezone_name": "not-a-zone"},
    {"timezone_name": "/etc/passwd"}, {"from_day": "2026-1-1"},
    {"through_day": "2026-10-18"}, {"through_day": "2100-01-01"},
    {"from_day": "2026-02-30"}, {"timezone_name": None},
])
def test_consent_alias_timezone_and_range_gates(kwargs):
    with pytest.raises(ValueError):
        summary([row()], **kwargs)


def test_input_size_and_row_caps(monkeypatch):
    data = export([row(), row("2026-10-19T19:00:00Z")])
    monkeypatch.setattr(anki, "MAX_ROWS", 1)
    with pytest.raises(ValueError):
        anki.parse_revlog(data)
    monkeypatch.setattr(anki, "MAX_BYTES", 2)
    with pytest.raises(ValueError):
        anki.parse_revlog(data)


def test_privacy_reports_only_counts_not_ids_timestamps_or_contents():
    marker = 7654321987654
    result = summary([row(cid=marker)])
    text = json.dumps(result)
    assert str(marker) not in text
    assert str(millis("2026-10-19T18:00:00Z")) not in text
    assert "deck_name" not in result
    assert all(value is False for value in result["privacy"].values())


def test_bridge_default_v1_is_preserved_and_optional_learning_is_versioned():
    baseline = preview()
    assert baseline["schema"] == "loop-noop-preview.v1"
    assert all("learning_on_source_day" not in r for r in baseline["observations"])
    combined = preview(summary([row()]))
    assert combined["schema"] == "loop-noop-preview.v2"
    first, second = combined["observations"]
    assert first["source_local_day"] == DAY
    assert first["outcome_wake_day"] == "2026-10-20"
    assert first["learning_on_source_day"]["rated_events"] == 1
    assert second["learning_on_source_day"] is None  # Outside the selected Anki export window.
    assert combined["noop_write_performed"] is False
    assert combined["target_catalog_verified"] is False
    assert combined["provenance"]["learning_report"]["join"] == "source_local_day_not_outcome_wake_day"


def test_learning_identity_stable_revision_changes_and_habit_state_is_independent():
    one, two = preview(summary([row()])), preview(summary([row(ease=1)]))
    a, b = [x["observations"][0] for x in (one, two)]
    assert a["observation_id"] == b["observation_id"]
    assert a["explicit_journal_answer_preview"] is b["explicit_journal_answer_preview"] is True
    assert a["learning_on_source_day"]["observation_id"] == b["learning_on_source_day"]["observation_id"]
    assert a["learning_on_source_day"]["revision_id"] != b["learning_on_source_day"]["revision_id"]
    assert one["provenance"]["learning_report"]["summary_sha256"] != two["provenance"]["learning_report"]["summary_sha256"]


def test_bridge_whitelists_nested_fields_and_never_echoes_private_strings():
    report = summary([row()])
    report["private-notes"] = "SECRET-NOTE"
    report["source"]["deck_name"] = "SECRET-DECK"
    report["daily"][DAY]["card"] = "SECRET-CARD"
    report["daily"][DAY]["by_kind"]["raw_app"] = "SECRET-APP"
    report["daily"][DAY]["first_scheduled_reviews"]["content"] = "SECRET-CONTENT"
    combined = preview(report)
    assert "SECRET" not in json.dumps(combined)


@pytest.mark.parametrize("path,value", [
    (("schema",), "anki-review-summary.v99"), (("mode",), "write"),
    (("source", "timezone"), "UTC"), (("source", "day_attribution"), "anki-4am"),
    (("source", "coverage"), "complete"), (("source", "source_instance"), "a secret deck"),
    (("provenance", "csv_sha256"), "invalid"), (("daily",), []),
    (("daily", DAY, "rated_events"), True), (("daily", DAY, "rated_events"), 2),
    (("daily", DAY, "unique_cards"), 0), (("daily", DAY, "timed_events"), 2),
    (("daily", DAY, "status"), "validated_recall"),
    (("daily", DAY, "buttons", "3"), -1),
    (("daily", DAY, "recorded_answer_seconds"), float("inf")),
    (("daily", DAY, "recorded_answer_seconds"), 0),
    (("daily", DAY, "first_scheduled_reviews", "rated_recall_fraction"), float("nan")),
    (("daily", DAY, "first_scheduled_reviews", "rated_recall_fraction"), True),
    (("daily", DAY, "first_scheduled_reviews", "count"), 2),
    (("daily", DAY, "first_scheduled_reviews", "again_count"), 1),
])
def test_summary_contract_rejects_wrong_source_or_inconsistent_counts(path, value):
    report = summary([row()])
    target = report
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        preview(report)


def test_zero_denominator_and_unknown_timing_validation():
    result = summary([])
    anki.daily_for_bridge(result, "America/Chicago")
    result["daily"][DAY]["first_scheduled_reviews"]["rated_recall_fraction"] = 0
    with pytest.raises(ValueError):
        anki.daily_for_bridge(result, "America/Chicago")
    result = summary([])
    result["daily"][DAY]["recorded_answer_seconds"] = 0
    with pytest.raises(ValueError):
        anki.daily_for_bridge(result, "America/Chicago")


def run_cli(script, *args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
                          cwd=ROOT, capture_output=True, text=True)


def cli_args(csv_path, output):
    return [csv_path, "--source-instance", "anki-local", "--timezone", "America/Chicago",
            "--from-day", DAY, "--through-day", DAY, "--consent", "local-preview-only", "--output", output]


def test_real_cli_to_cli_pipeline_leaves_sources_unchanged_and_uses_private_files(tmp_path):
    csv_path, anki_path = tmp_path / "revlog.csv", tmp_path / "anki.json"
    csv_path.write_bytes(export([row()]))
    before = csv_path.read_bytes()
    result = run_cli("research_anki_outcomes.py", *cli_args(csv_path, anki_path))
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert csv_path.read_bytes() == before
    if os.name != "nt":
        assert anki_path.stat().st_mode & 0o777 == 0o600
    summary_before = anki_path.read_bytes()
    checkmarks, mapped, output = tmp_path / "checkmarks.csv", tmp_path / "mapping.json", tmp_path / "preview.json"
    checkmarks.write_text("Date,Value,Notes\n2026-10-19,NO,private-text\n")
    mapped.write_text(json.dumps(mapping()))
    result = run_cli("research_loop_bridge.py", checkmarks, "--mapping", mapped,
                     "--from-day", DAY, "--through-day", DAY,
                     "--anki-report", anki_path, "--output", output)
    assert result.returncode == 0, result.stderr
    combined = json.loads(output.read_text())
    assert combined["observations"][0]["explicit_journal_answer_preview"] is False
    assert combined["observations"][0]["learning_on_source_day"]["rated_events"] == 1
    assert "private-text" not in output.read_text()
    assert anki_path.read_bytes() == summary_before
    original = output.read_bytes()
    refused = run_cli("research_loop_bridge.py", checkmarks, "--mapping", mapped,
                      "--from-day", DAY, "--through-day", DAY,
                      "--anki-report", anki_path, "--output", output)
    assert refused.returncode == 2
    assert output.read_bytes() == original


def test_cli_refuses_overwrite_source_symlink_and_hardlink(tmp_path):
    source = tmp_path / "revlog.csv"
    source.write_bytes(export([row()]))
    before = source.read_bytes()
    for mode in ("same", "symlink", "hardlink"):
        output = source if mode == "same" else tmp_path / mode
        if mode == "symlink":
            output.symlink_to(source)
        elif mode == "hardlink":
            os.link(source, output)
        result = run_cli("research_anki_outcomes.py", *cli_args(source, output))
        assert result.returncode == 2
        assert source.read_bytes() == before


def test_cli_redacts_bad_data_and_paths_from_errors(tmp_path):
    source = tmp_path / "PRIVATE-PATH.csv"
    source.write_bytes(export([row(ease="PRIVATE-CONTENT")]))
    result = run_cli("research_anki_outcomes.py", *cli_args(source, tmp_path / "out.json"))
    assert result.returncode == 2
    assert "PRIVATE" not in result.stderr
    assert "Traceback" not in result.stderr
    assert result.stdout == ""
    assert not (tmp_path / "out.json").exists()


def test_cli_requires_explicit_consent(tmp_path):
    source = tmp_path / "revlog.csv"
    source.write_bytes(export([row()]))
    args = cli_args(source, tmp_path / "out.json")
    i = args.index("--consent")
    del args[i:i + 2]
    assert run_cli("research_anki_outcomes.py", *args).returncode == 2
    assert not (tmp_path / "out.json").exists()


def test_randomized_aggregate_invariants_and_input_order_independence():
    import random
    rng = random.Random(20261020)
    records = [row(id=millis("2026-10-19T12:00:00Z") + i * 1000,
                   cid=rng.randrange(1, 40), ease=rng.randrange(0, 5),
                   kind=rng.randrange(0, 6), elapsed=rng.choice([0, 1000, 2000]))
               for i in range(1500)]
    result = summary(records)
    rng.shuffle(records)
    assert summary(records)["daily"] == result["daily"]
    sanitized, _ = anki.daily_for_bridge(result, "America/Chicago")
    d = sanitized[DAY]
    assert d["rated_events"] + d["non_answer_events"] == 1500
    assert sum(d["by_kind"].values()) == sum(d["buttons"].values()) == d["rated_events"]
    assert d["first_scheduled_reviews"]["count"] <= d["unique_cards"] <= 39


def test_bridge_rejects_duplicate_json_and_nonfinite_constants_at_cli_boundary(tmp_path):
    checkmarks, mapped, report = tmp_path / "c.csv", tmp_path / "m.json", tmp_path / "a.json"
    checkmarks.write_text("Date,Value,Notes\n2026-10-19,YES_AUTO,\n")
    mapped.write_text(json.dumps(mapping()))
    for payload in ('{"schema":"x","schema":"y"}', '{"x":NaN}'):
        report.write_text(payload)
        result = run_cli("research_loop_bridge.py", checkmarks, "--mapping", mapped,
                         "--from-day", DAY, "--through-day", DAY, "--anki-report", report)
        assert result.returncode == 2
        assert result.stdout == ""
        assert "Traceback" not in result.stderr


def test_anki_data_cannot_autocomplete_loop_unknown_or_skipped_days():
    for state in ("YES_AUTO", "SKIP", "UNKNOWN"):
        result = bridge.build_preview(f"Date,Value,Notes\n{DAY},{state},\n".encode(),
                                      mapping(), DAY, DAY, anki_report=summary([row()]))
        assert result["observations"][0]["explicit_journal_answer_preview"] is None
        assert result["observations"][0]["source_state"] == state
