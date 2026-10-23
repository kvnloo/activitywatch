"""Synthetic interoperability tests; no personal habit, health or activity data."""
import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from scripts import research_loop_bridge as bridge


@pytest.fixture
def mapping():
    return {
        "schema": bridge.MAPPING_SCHEMA, "consent":"local-preview-only",
        "source_instance":"loop-test-device", "habit_key":"habit-001",
        "habit_type":"boolean", "noop_factor_key":"Synthetic existing Journal question?",
        "timezone":"America/Chicago", "wake_day_offset":1,
        "value_encoding":"loop-named-v1",
    }


def csv_data(*rows):
    stream=io.StringIO(newline="")
    writer=csv.writer(stream)
    writer.writerow(["Date","Value","Notes"])
    writer.writerows(rows)
    return stream.getvalue().encode()


def preview(mapping, data, first="2026-10-19", last="2026-10-19", aw=None):
    return bridge.build_preview(data,mapping,first,last,aw)


def aw_report(**metrics):
    return {
        "schema":"activitywatch.flow-proxies.v0",
        "source":{"timezone":"America/Chicago","day_attribution":"local-midnight-split-v1",
                  "window_bucket":"PRIVATE-HOST"},
        "daily":{"2026-10-19":metrics},
    }


@pytest.mark.parametrize("state,answer",[("YES_MANUAL",True),("NO",False),
    ("YES_AUTO",None),("SKIP",None),("UNKNOWN",None),("",None)])
def test_states_are_not_flattened(mapping,state,answer):
    result=preview(mapping,csv_data(["2026-10-19",state,"PRIVATE NOTES"]))
    row=result["observations"][0]
    assert row["explicit_journal_answer_preview"] is answer
    assert row["source_state"]==(state or "UNKNOWN")
    assert row["event_timestamp_utc"] is None
    assert result["noop_write_performed"] is False
    assert result["target_catalog_verified"] is False
    assert "PRIVATE NOTES" not in json.dumps(result)


def test_unlogged_day_is_not_no(mapping):
    result=preview(mapping,csv_data(["2026-10-18","NO",""]))
    assert result["observations"][0]["source_state"]=="UNLOGGED"
    assert result["observations"][0]["explicit_journal_answer_preview"] is None


@pytest.mark.parametrize("state",["2","1","0","3","-1","1000","NaN","yes","BROKEN"])
def test_numeric_or_unknown_export_formats_fail_closed(mapping,state):
    with pytest.raises(ValueError):
        preview(mapping,csv_data(["2026-10-19",state,""]))


@pytest.mark.parametrize("key,value",[("consent",False),("consent","yes"),
    ("habit_type","numeric"),("value_encoding","integer"),("wake_day_offset",True),
    ("wake_day_offset",2),("timezone","Unknown/Zone"),("noop_factor_key",""),
    ("habit_key","private habit title"),("schema","v2")])
def test_invalid_mapping_is_rejected(mapping,key,value):
    mapping[key]=value
    with pytest.raises(ValueError):
        preview(mapping,csv_data())


def test_no_unrecognized_mapping_fields(mapping):
    mapping["auto_write_to_noop"]=True
    with pytest.raises(ValueError): preview(mapping,csv_data())


def test_identical_duplicate_dates_are_deduplicated_without_notes(mapping):
    result=preview(mapping,csv_data(["2026-10-19","NO","one"],["2026-10-19","NO","two"]))
    assert len(result["observations"])==1
    assert result["summary"]["identical_duplicate_rows"]==1


def test_conflicting_duplicates_are_not_order_dependent(mapping):
    for states in [("NO","YES_MANUAL"),("YES_MANUAL","NO")]:
        with pytest.raises(ValueError):
            preview(mapping,csv_data(*[["2026-10-19",s,""] for s in states]))


def test_repeat_export_and_reordering_have_stable_observation_ids(mapping):
    a=["2026-10-18","NO",""]
    b=["2026-10-19","YES_MANUAL","PRIVATE"]
    first=preview(mapping,csv_data(a,b),"2026-10-18")
    second=preview(mapping,csv_data(b,a),"2026-10-18")
    assert first["observations"]==second["observations"]
    assert first["provenance"]["csv_sha256"]!=second["provenance"]["csv_sha256"]


def test_changed_answer_keeps_identity_and_changes_revision(mapping):
    a=preview(mapping,csv_data(["2026-10-19","NO",""]))["observations"][0]
    b=preview(mapping,csv_data(["2026-10-19","YES_MANUAL",""]))["observations"][0]
    assert a["observation_id"]==b["observation_id"]
    assert a["revision_id"]!=b["revision_id"]


@pytest.mark.parametrize("day,wake",[("2026-12-31","2027-01-01"),
    ("2028-02-28","2028-02-29"),("2028-02-29","2028-03-01"),
    ("2026-03-08","2026-03-09"),("2026-11-01","2026-11-02")])
def test_calendar_offsets_not_24_hour_timestamp_shifts(mapping,day,wake):
    row=preview(mapping,csv_data([day,"NO",""]),day,day)["observations"][0]
    assert row["outcome_wake_day"]==wake
    assert row["event_timestamp_utc"] is None


def test_same_day_requires_explicit_mapping(mapping):
    mapping["wake_day_offset"]=0
    row=preview(mapping,csv_data(["2026-10-19","NO",""]))["observations"][0]
    assert row["outcome_wake_day"]==row["source_local_day"]


@pytest.mark.parametrize("first,last",[("2026-10-20","2026-10-19"),
    ("2000-01-01","2026-10-19"),("2026-02-29","2026-03-01"),
    ("20261019","2026-10-19"),("9999-12-31","9999-12-31")])
def test_invalid_calendar_ranges(mapping,first,last):
    with pytest.raises(ValueError): preview(mapping,csv_data(),first,last)


def test_csv_quotes_bom_newlines_and_private_notes(mapping):
    data=b'\xef\xbb\xbf'+csv_data(["2026-10-19","YES_MANUAL",'PRIVATE,"quoted"\nnext line'])
    result=preview(mapping,data)
    assert result["observations"][0]["explicit_journal_answer_preview"] is True
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.parametrize("data",[b'Date,SecretHabit,\n2026-10-19,YES_MANUAL,\n',
    b'Date,Value,Notes\n2026-10-19,NO,,extra\n',b'\xff',
    b'Date,Value,Notes\n2026-02-30,NO,\n'])
def test_wrong_or_malformed_csv_rejected(mapping,data):
    with pytest.raises(ValueError): preview(mapping,data)


def test_activity_allowlist_excludes_raw_identity(mapping):
    aw=aw_report(active_seconds=600,observed_window_seconds=300,
        window_coverage_of_active=0.5,context_switch_count=2,fragmentation_simpson=.2,
        title="PRIVATE TITLE",url="PRIVATE URL",app="PRIVATE APP")
    result=preview(mapping,csv_data(),aw=aw)
    assert "PRIVATE" not in json.dumps(result)
    metrics=result["observations"][0]["activity_on_source_day"]
    assert metrics["context_switch_count"]==2
    assert metrics["status"]=="observed"


def test_missing_activity_and_zero_observation_are_not_no_switch(mapping):
    no_report=preview(mapping,csv_data())
    assert no_report["observations"][0]["activity_on_source_day"] is None
    aw=aw_report(active_seconds=60,observed_window_seconds=0,context_switch_count=0,
                 fragmentation_simpson=0,sustained_context_seconds=0)
    result=preview(mapping,csv_data(),aw=aw)["observations"][0]["activity_on_source_day"]
    assert result["status"]=="not_observed"
    assert result["context_switch_count"] is None
    assert result["fragmentation_simpson"] is None


@pytest.mark.parametrize("value",[float("nan"),float("inf"),-1,True,"PRIVATE"])
def test_invalid_activity_values(mapping,value):
    with pytest.raises(ValueError):
        preview(mapping,csv_data(),aw=aw_report(active_seconds=value))


def test_wrong_timezone_and_old_day_recipe_are_not_silently_joined(mapping):
    for field,value in [("timezone","UTC"),("day_attribution","start-day-v0")]:
        report=aw_report()
        report["source"][field]=value
        with pytest.raises(ValueError): preview(mapping,csv_data(),aw=report)


def test_activity_join_is_on_action_date_not_the_wake_day(mapping):
    report=aw_report(active_seconds=10,observed_window_seconds=10,context_switch_count=1)
    report["daily"]["2026-10-20"]={"active_seconds":20,"observed_window_seconds":20,"context_switch_count":4}
    row=preview(mapping,csv_data(["2026-10-19","NO",""]),aw=report)["observations"][0]
    assert row["outcome_wake_day"]=="2026-10-20"
    assert row["activity_on_source_day"]["context_switch_count"]==1


def test_read_limits(mapping,monkeypatch):
    monkeypatch.setattr(bridge,"MAX_ROWS",1)
    with pytest.raises(ValueError):
        preview(mapping,csv_data(["2026-10-18","NO",""],["2026-10-19","NO",""]))


@pytest.mark.parametrize("raw",[b'{"a":1,"a":2}',b'{"x":NaN}',b'{"x":Infinity}',b'\xff'])
def test_invalid_json_is_rejected(raw):
    with pytest.raises(ValueError): bridge._load_json(raw)


def test_cli_never_mutates_inputs_or_overwrites_reports(mapping,tmp_path,capsys):
    data=csv_data(["2026-10-19","NO","PRIVATE NOTES"])
    source=tmp_path/'Checkmarks.csv'; source.write_bytes(data)
    config=tmp_path/'mapping.json'; config.write_text(json.dumps(mapping))
    output=tmp_path/'preview.json'
    args=[str(source),'--mapping',str(config),'--from-day','2026-10-19','--through-day','2026-10-19','--output',str(output)]
    assert bridge.main(args)==0
    first=output.read_bytes()
    assert source.read_bytes()==data
    assert "PRIVATE" not in output.read_text()
    if os.name=='posix': assert output.stat().st_mode & 0o777==0o600
    with pytest.raises(SystemExit) as exc: bridge.main(args)
    assert exc.value.code==2
    assert output.read_bytes()==first
    with pytest.raises(SystemExit): bridge.main(args[:-1]+[str(source)])
    assert source.read_bytes()==data


def test_cli_private_error_payload_is_not_logged(mapping,tmp_path,capsys):
    source=tmp_path/'Checkmarks.csv'; source.write_bytes(csv_data(["2026-10-19","PRIVATE SECRET","PRIVATE NOTES"]))
    config=tmp_path/'mapping.json'; config.write_text(json.dumps(mapping))
    with pytest.raises(SystemExit) as exc:
        bridge.main([str(source),'--mapping',str(config),'--from-day','2026-10-19','--through-day','2026-10-19'])
    assert exc.value.code==2
    captured=capsys.readouterr()
    assert not captured.out
    assert "PRIVATE" not in captured.err


def test_real_analysis_cli_to_readonly_bridge(mapping,tmp_path):
    """Run both production CLIs on synthetic files; no model-reimplemented joins."""
    root=Path(__file__).resolve().parents[2]
    raw={"buckets":{
        "w":{"type":"currentwindow","events":[{"timestamp":"2026-10-19T23:50:00-05:00","duration":1800,"data":{"app":"PrivateEditor","title":"PRIVATE"}}]},
        "a":{"type":"afkstatus","events":[{"timestamp":"2026-10-19T23:50:00-05:00","duration":1800,"data":{"status":"not-afk"}}]},
    }}
    export=tmp_path/'aw.json'; export.write_text(json.dumps(raw))
    report=tmp_path/'aw-report.json'
    subprocess.run([sys.executable,str(root/'scripts/research_flow_metrics.py'),str(export),
                    '--timezone','America/Chicago','--output',str(report)],check=True,capture_output=True)
    config=tmp_path/'mapping.json'; config.write_text(json.dumps(mapping))
    checkmarks=tmp_path/'Checkmarks.csv'; checkmarks.write_bytes(csv_data(["2026-10-19","YES_MANUAL","PRIVATE"]))
    output=tmp_path/'joined.json'
    subprocess.run([sys.executable,str(root/'scripts/research_loop_bridge.py'),str(checkmarks),
        '--mapping',str(config),'--from-day','2026-10-19','--through-day','2026-10-20',
        '--activity-report',str(report),'--output',str(output)],check=True,capture_output=True)
    joined=json.loads(output.read_text())
    assert joined['observations'][0]['activity_on_source_day']['observed_window_seconds']==600
    assert joined['observations'][1]['activity_on_source_day']['observed_window_seconds']==1200
    assert joined['observations'][0]['outcome_wake_day']=='2026-10-20'
    assert joined['observations'][1]['explicit_journal_answer_preview'] is None
    assert 'PRIVATE' not in output.read_text()
    assert 'PrivateEditor' not in output.read_text()
    assert export.read_text()==json.dumps(raw)
