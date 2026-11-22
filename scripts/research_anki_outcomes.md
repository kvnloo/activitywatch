# Local Anki review evidence (downstream research only)

This adapter extends the existing Loop / ActivityWatch evidence preview. **It is
not a watcher, live Anki connector, NOOP importer, scheduler or recommendation
engine.** No network, SQLite, AnkiConnect, collection mutation, note/card/deck
reading, FSRS optimization or ActivityWatch bucket writes occur. The user selects
one already-exported CSV. All examples below use synthetic or local data.

## Source and meaning

Anki's official [manual analysis documentation](https://docs.ankiweb.net/manual/stats)
and [revlog definitions](https://github.com/ankitects/anki/blob/main/rslib/src/revlog/mod.rs)
are the field references. The reviewed revlog definition blob was
`3e22890b10c1cb5f15acd08d53351e1d36b39b8e` on October 20, 2026. Credit Ankitects and
Anki contributors for the underlying review model and ActivityWatch contributors
for the existing research tooling. No Anki source code is copied here.

Only a native nine-column `revlog` CSV is accepted (column order may vary):

```text
id,cid,usn,ease,ivl,lastIvl,factor,time,type
```

Use a trusted local SQLite exporter on an **offline copy**, not your live Anki
collection. Export the `revlog` table with its header. Do not upload either your
collection or its CSV to this repository or an agent conversation. This script
cannot export a collection itself. Card/note text exports, `.apkg`, `.colpkg`,
JSON, unknown columns, numeric prefixes, non-integer values and unsupported
review kinds fail closed. Limit: 32 MiB / 200,000 input records / 3,660 output days.
Exports larger than that need an explicitly bounded research window; the tool
never truncates silently.

- `id` is a UTC Unix **millisecond** timestamp/review identity. It is NOT seconds.
  `cid` is used only in memory to count unique cards and select a first rating.
  Neither identifier is emitted. Deck names, content, tags and media are absent
  from the accepted input format.
- Kinds 0/1/2/3 are learning/review/relearning/filtered. Types 4 and 5, and any row
  with `ease=0`, are non-answer operations, not successes or failures.
- Raw buttons 1–4 are counted separately; we do not relabel historical learning
  events because the old V1 scheduler used 3 for Easy. For the narrowly scoped
  **first scheduled review rating per card/civil-day**, button 1 is Again, and
  buttons 2–4 contribute a self-rated pass. A later successful retry cannot erase
  an earlier failed first rating. If that day's first rated event is learning,
  relearning or filtered, that card does not enter the scheduled-first metric.
- This is **not Anki's True Retention**. We use explicit local midnight, not Anki's
  configurable scheduler rollover, and intentionally exclude filtered/relearning
  first events. Ratings are self-report, not objective correctness, transfer,
  general intelligence, or measured retention at 24 hours / seven days.
- `ivl`/`lastIvl` may be positive days or negative seconds. They are validated but
  never misused as elapsed intervals for a delayed-retention calculation. FSRS
  enablement, parameters, stability and retrievability are not inferred.
- `time` is recorded answer time, potentially capped by Anki, **not session or
  focus duration**. Zero is treated as unavailable timing, never a measured zero.
- Export completeness is unverified. An empty day is
  `no_rated_reviews_in_export`, not proof of no studying, a failed habit, or zero
  retention. Outside-window records are counted in provenance, not reassigned.

## Generate a private aggregate

```sh
python scripts/research_anki_outcomes.py /private/revlog.csv \
  --consent local-preview-only --source-instance anki-local \
  --timezone America/Chicago --from-day 2026-10-19 --through-day 2026-10-20 \
  --output /private/anki-summary.json
```

Output: `anki-review-summary.v1`. Only daily aggregates, explicit limits, opaque
source alias and CSV hash are emitted. Repeated identical review IDs are counted
once; conflicting duplicates reject the whole file. CSV order does not change
the selected first rating. UTC conversion handles DST folds/gaps, leap day and
New Year without assuming 24-hour days. Existing outputs (including symlinks or
hardlinks to inputs) are never replaced; new files request mode 0600. File modes
are platform-dependent, not a substitute for secure local storage. Errors do not
echo private rows or paths.

## Compose with the existing Loop / ActivityWatch preview

Use the same explicit Loop mapping as documented in
[research_loop_bridge.md](research_loop_bridge.md). Select an existing NOOP
Journal question yourself; its existence is still **not verified** by the bridge.

```sh
python scripts/research_loop_bridge.py /private/Checkmarks.csv \
  --mapping /private/loop-mapping.json \
  --from-day 2026-10-19 --through-day 2026-10-20 \
  --activity-report /private/activity-summary.json \
  --anki-report /private/anki-summary.json \
  --output /private/combined-preview.json
```

`--activity-report` remains optional. The Anki argument is also optional: without
it, the existing **v1 output is unchanged**. With it, output is explicitly
`loop-noop-preview.v2`, with `learning_on_source_day` on each observation and
validated learning provenance. It joins Anki and ActivityWatch to the **source
local day**, not the following sleep/wake outcome day. Different timezones,
non-midnight attribution, malformed counters/fractions, and inconsistent ranges
are rejected rather than shifted or filled. Missing Anki report days remain null.
Arbitrary added fields are never forwarded.

A local learning observation gets a stable hash of source alias/timezone/day and
its own revision hash of the sanitized counters. The original Loop observation
identity and answer are independent. New Anki evidence cannot turn Loop
`YES_AUTO`, `SKIP`, `UNKNOWN` or an absent day into a manual Yes/No. The combined
preview contains no raw review/card IDs, deck labels or Loop notes. Hashes provide
change tracking, not independent authentication of user-supplied source data.

## Verification and next gate

```sh
python -m pytest scripts/tests/test_research_*.py -q
```

The suite includes actual CLI → CLI subprocess tests, DST/year/leap boundaries,
manual/rescheduled exclusions, failed-then-passed retries, record deduplication,
malformed numeric fields, privacy allowlists, consent and non-overwrite checks.
All fixtures are synthetic. The existing focused hosted CI covers Python 3.11
and 3.13 via the `test_research_*.py` glob.

Before personal inference, Hermes should locally export a small user-approved
revlog period, inspect the native fields, run the tools, and compare source
counts/UTC dates with the aggregates (allowing for Anki scheduler-day differences).
Keep raw exports local and preserve backups. No real-data correctness, live sync,
beneficial intervention, causal relation or 24h/7d retention has been established.
Keep this work on the existing fork PR #2; NOOP #70 owns cross-app coordination.
