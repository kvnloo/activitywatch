# Offline Anki SQLite snapshot → local review aggregate

This fork-only, read-only, opt-in native helper replaces the manual revlog CSV
export step of the existing Anki review adapter. It is not a flashcard generator,
Anki add-on, live connector, scheduler, held-out recall test or clinical metric.

Prepare a checkpointed, standalone *offline* SQLite copy with Anki closed,
using a trusted local backup procedure. Never pass the open/live collection.
Rejects symlinks, hardlinks, and adjacent SQLite -wal, -shm, or -journal files.
Reads only nine integer revlog fields with SQLite mode=ro&immutable=1, never
card/note/deck text, and detects source changes during extraction. It cannot
prove a selected file is actually offline or that its history is complete.

Limits: 1 GiB input database, 200,000 rows, 32 MiB in-memory CSV (never
written to disk), 3,660 report days. Outputs are owner-readable (0600 where
supported), create-only local JSON. Never upload the copy, summary, or other
personal telemetry to GitHub or conversation threads.

Local CLI:

    python3 scripts/research_anki_sqlite_copy.py /private/checkpointed-copy.anki2 \
      --consent local-preview-only --source-instance anki-offline \
      --timezone America/Chicago --from-day 2026-10-19 \
      --through-day 2026-10-20 --output /private/review-aggregate.json

Optional compose with the existing explicit Loop/ActivityWatch preview:

    python3 scripts/research_loop_bridge.py /private/Checkmarks.csv \
      --mapping /private/loop-mapping.json \
      --from-day 2026-10-19 --through-day 2026-10-20 \
      --anki-report /private/review-aggregate.json --output /private/combined.json

Native tests:

    python3 -m pytest -q scripts/tests/test_research_anki_sqlite_copy.py

The emitted CSV digest fingerprints only the ephemeral selected revlog rows,
not the whole SQLite file. Summary values remain **Anki review-button
self-ratings**, not FSRS predictions, independently demonstrated mastery,
delayed 24h/7d recall, or a causal benefit from ActivityWatch screen time.
Missing days are unknown, not failed reviews. A separately consented held-out
objective recall instrument remains necessary.

Credit: Damien Elmes, Ankitects, and Anki contributors own original revlog
semantics; Erik and Johan Bjäreholt and ActivityWatch contributors own the
telemetry foundation. This Python standard-library adapter reuses the existing
summary contract without copying Anki implementation or changing licenses.
Origin-facing publication remains unapproved.
