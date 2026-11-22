"""Native, entirely synthetic SQLite integration regressions for opt-in offline Anki read."""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from scripts import research_anki_sqlite_copy as bridge


def make_copy(tmp_path: Path, *, columns=bridge.REVLOG_COLUMNS, rows=()) -> Path:
    source = tmp_path / "snapshot.anki2"
    with sqlite3.connect(source) as db:
        schema = ", ".join(f'"{name}" INTEGER' for name in columns)
        db.execute(f"CREATE TABLE revlog ({schema})")
        for row in rows:
            db.execute(f"INSERT INTO revlog VALUES ({','.join('?' for _ in row)})", row)
    return source


def row(iso="2026-10-19T16:00:00Z", cid=31, ease=1, kind=1):
    stamp = int(datetime.fromisoformat(iso.replace('Z','+00:00')).timestamp() * 1000)
    return stamp, cid, 0, ease, 1, 2, 2500, 1500, kind


def test_real_sqlite_extract_native_columns_in_order_without_extra_tables(tmp_path):
    p = make_copy(tmp_path, columns=tuple(reversed(bridge.REVLOG_COLUMNS)), rows=[tuple(reversed(row()))])
    with sqlite3.connect(p) as db:
        db.execute('CREATE TABLE notes (secret TEXT)')
        db.execute('INSERT INTO notes VALUES (?)', ('PRIVATE CARD CONTENT',))
    data = bridge.extract_revlog_csv(p)
    assert b'PRIVATE CARD CONTENT' not in data
    record = list(csv.reader(io.StringIO(data.decode('ascii'))))
    assert record[0] == list(bridge.REVLOG_COLUMNS)
    assert record[1] == [str(x) for x in row()]


def test_negative_control_native_sqlite_is_not_a_raw_nine_column_csv(tmp_path):
    p = make_copy(tmp_path, rows=[row()])
    with pytest.raises((UnicodeError, csv.Error, ValueError)):
        # SQLite starts with a binary header; revlog CSV consumers cannot parse it.
        data = p.read_bytes().decode('utf-8')
        parsed = list(csv.reader(io.StringIO(data), strict=True))
        if not parsed or tuple(parsed[0]) != bridge.REVLOG_COLUMNS:
            raise ValueError('native SQLite cannot be parsed as a raw CSV')


def test_copy_not_changed_and_no_wal_sidecars_created(tmp_path):
    p = make_copy(tmp_path, rows=[row()])
    before = p.read_bytes()
    bridge.extract_revlog_csv(p)
    assert p.read_bytes() == before
    assert not list(tmp_path.glob('*-wal'))
    assert not list(tmp_path.glob('*-shm'))


@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal'])
def test_fails_closed_on_unclean_backup_sidecar(tmp_path, suffix):
    p = make_copy(tmp_path)
    Path(f'{p}{suffix}').write_bytes(b'unsafe')
    with pytest.raises(ValueError, match='sidecars'):
        bridge.extract_revlog_csv(p)


def test_no_symlink_or_hardlink_alias(tmp_path):
    p = make_copy(tmp_path)
    alias = tmp_path / 'alias.anki2'
    alias.symlink_to(p)
    with pytest.raises(ValueError, match='symlinks'):
        bridge.extract_revlog_csv(alias)
    alias.unlink()
    os.link(p, alias)
    with pytest.raises(ValueError, match='symlinks'):
        bridge.extract_revlog_csv(p)


def test_non_native_schema_rejected(tmp_path):
    p = make_copy(tmp_path, columns=('id', 'cid'))
    with pytest.raises(ValueError, match='native nine-column'):
        bridge.extract_revlog_csv(p)


def test_rejects_non_integer_cards_without_emitting_content(tmp_path):
    p = make_copy(tmp_path)
    with sqlite3.connect(p) as db:
        db.execute('INSERT INTO revlog VALUES (?,?,?,?,?,?,?,?,?)', (*row()[:-1], 'SENSITIVE'))
    with pytest.raises(ValueError, match='non-integer'):
        bridge.extract_revlog_csv(p)


def test_bounded_rows_fails_closed(tmp_path, monkeypatch):
    p = make_copy(tmp_path, rows=[row(), row('2026-10-19T16:00:01Z')])
    monkeypatch.setattr(bridge, 'MAX_ROWS', 1)
    with pytest.raises(ValueError, match='row limit'):
        bridge.extract_revlog_csv(p)


def test_private_output_create_only_and_no_personal_content(tmp_path):
    p = tmp_path / 'summary.json'
    summary = {'schema': 'anki-review-summary.v1', 'daily': {'2026-10-19': {'first_scheduled_reviews': {'count': 1}}}}
    bridge.write_private_report(p, summary)
    assert json.loads(p.read_text()) == summary
    assert p.stat().st_mode & 0o077 == 0
    with pytest.raises(FileExistsError):
        bridge.write_private_report(p, {'secret': 'DO NOT OVERWRITE'})
    assert 'DO NOT OVERWRITE' not in p.read_text()


def test_real_cli_offline_snapshot_to_anki_daily_summary(tmp_path):
    """Native SQLite → existing Anki aggregator; no raw card data on disk."""
    import subprocess
    import sys
    snapshot = make_copy(tmp_path, rows=[row(), row('2026-10-19T16:01:00Z', ease=3)])
    output = tmp_path / 'private-summary.json'
    command = [sys.executable, 'scripts/research_anki_sqlite_copy.py', str(snapshot),
               '--consent', 'local-preview-only', '--source-instance', 'offline-copy',
               '--timezone', 'UTC', '--from-day', '2026-10-19',
               '--through-day', '2026-10-19', '--output', str(output)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report['daily']['2026-10-19']['first_scheduled_reviews'] == {
        'count': 1, 'again_count': 1, 'pass_count': 0, 'rated_recall_fraction': 0.0}
    assert report['provenance']['input_kind'] == 'checkpointed_offline_sqlite_copy'
    assert report['source']['coverage'] == 'export_only_completeness_unverified'
    assert not any(k in report for k in ('notes', 'cards', 'decks'))
    assert 'offline_copy_completeness_and_origin_unverified' in report['limitations']
    assert output.stat().st_mode & 0o077 == 0
    second = subprocess.run(command, capture_output=True, text=True)
    assert second.returncode == 2
    assert 'output already exists' in second.stderr
    assert not (tmp_path / 'snapshot.anki2-wal').exists()


def test_cli_requires_opt_in_and_never_creates_output_without_consent(tmp_path):
    import subprocess
    import sys
    snapshot = make_copy(tmp_path, rows=[row()])
    output = tmp_path / 'private-summary.json'
    command = [sys.executable, 'scripts/research_anki_sqlite_copy.py', str(snapshot),
               '--source-instance', 'offline-copy', '--timezone', 'UTC',
               '--from-day', '2026-10-19', '--through-day', '2026-10-19',
               '--output', str(output)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0
    assert not output.exists()
