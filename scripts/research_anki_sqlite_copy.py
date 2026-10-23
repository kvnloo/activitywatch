#!/usr/bin/env python3
"""Read Anki review evidence from an explicitly selected *offline* SQLite copy.

This is local-only, read-only and not an Anki add-on or collection backup tool.
No Anki card text, note/deck data, scheduler state or database mutation is used.
See research_anki_outcomes.md for revlog interpretation and limitations.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

REVLOG_COLUMNS = ("id", "cid", "usn", "ease", "ivl", "lastIvl", "factor", "time", "type")
MAX_DB_BYTES = 1024 * 1024 * 1024  # Bounds untrusted offline input, not a recommended collection size.
MAX_ROWS = 200_000
MAX_CSV_BYTES = 32 * 1024 * 1024


def extract_revlog_csv(copy_path: Path) -> bytes:
    """Extract only numeric revlog fields in memory; never persist raw identifiers."""
    path = Path(copy_path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("expected a standalone regular offline copy (no symlinks/hardlinks)")
    if not 0 < before.st_size <= MAX_DB_BYTES:
        raise ValueError("offline copy exceeds size limit or is empty")
    # A live / uncheckpointed WAL copy would silently omit pending rows in immutable mode.
    if any(Path(f"{path}{suffix}").exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("offline copy contains SQLite sidecars; checkpoint a backup first")
    uri = path.absolute().as_uri() + "?mode=ro&immutable=1"
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(REVLOG_COLUMNS)
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=0.0)) as db:
            db.execute("PRAGMA query_only = ON")
            table = db.execute("SELECT type FROM sqlite_master WHERE name = 'revlog'").fetchall()
            if table != [("table",)]:
                raise ValueError("offline copy has no native revlog table")
            columns = [r[1] for r in db.execute("PRAGMA table_info(revlog)")]
            if set(columns) != set(REVLOG_COLUMNS) or len(columns) != len(REVLOG_COLUMNS):
                raise ValueError("offline copy does not contain the native nine-column revlog")
            query = "SELECT " + ", ".join('"' + col + '"' for col in REVLOG_COLUMNS)
            query += " FROM revlog ORDER BY id LIMIT ?"
            for index, row in enumerate(db.execute(query, (MAX_ROWS + 1,)), 1):
                if index > MAX_ROWS:
                    raise ValueError("offline revlog exceeds row limit")
                if not all(type(value) is int for value in row):
                    raise ValueError("revlog contains a non-integer field")
                writer.writerow(row)
                if output.tell() > MAX_CSV_BYTES:
                    raise ValueError("offline revlog exceeds bounded CSV input size")
    except sqlite3.DatabaseError:
        raise ValueError("cannot read the offline revlog copy") from None
    after = path.lstat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise ValueError("offline copy changed during extraction")
    if any(Path(f"{path}{suffix}").exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("offline copy gained a SQLite sidecar during extraction")
    return output.getvalue().encode("ascii")


def write_private_report(path: Path, report: dict) -> None:
    """Create an owner-readable-only JSON report, never replacing existing data."""
    data = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("offline_copy", type=Path, help="explicitly prepared, checkpointed SQLite copy (never live Anki)")
    parser.add_argument("--consent", required=True, choices=["local-preview-only"])
    parser.add_argument("--source-instance", required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--from-day", required=True)
    parser.add_argument("--through-day", required=True)
    parser.add_argument("--output", type=Path, required=True, help="new private aggregate JSON file")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError("output already exists")
        try:
            from scripts import research_anki_outcomes as anki
        except ImportError:  # Invoked as scripts/research_anki_sqlite_copy.py
            import research_anki_outcomes as anki
        raw = extract_revlog_csv(args.offline_copy)
        summary = anki.build_summary(
            raw, source_instance=args.source_instance, timezone_name=args.timezone,
            from_day=args.from_day, through_day=args.through_day, consent=args.consent,
        )
        # Do not claim this SQLite read is authenticated or an Anki scheduler day.
        summary["provenance"]["input_kind"] = "checkpointed_offline_sqlite_copy"
        summary["limitations"].append("offline_copy_completeness_and_origin_unverified")
        write_private_report(args.output, summary)
    except FileExistsError:
        parser.exit(2, "error: output already exists\n")
    except (ValueError, TypeError, OverflowError, OSError):
        parser.exit(2, "error: invalid offline SQLite copy or configuration\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
