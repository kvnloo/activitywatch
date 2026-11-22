# Loop → ActivityWatch → NOOP: read-only evidence preview

**Downstream research, not live sync, a NOOP importer, or a flow/health score.**
This tool lives beside the existing ActivityWatch research scripts, outside NOOP.
It writes no app database, ActivityWatch bucket, reminder schedule or Journal answer.
The only output is a new local JSON preview (or stdout). No network access is used.

Track this work in [ActivityWatch research PR #2](https://github.com/kvnloo/activitywatch/pull/2)
and [NOOP integration issue #70](https://github.com/kvnloo/noop/issues/70).
[Loop focus-shield PR #3](https://github.com/kvnloo/uhabits/pull/3) remains a separate
intervention experiment, not proof that reminders were acted on or habits completed.

## Source contract and attribution

Loop's export writes **computed** checkmarks, not a lossless history of original
answers. Its current `Entry.formattedValue` writes `YES_MANUAL`, `YES_AUTO`, `NO`,
`SKIP`, and `UNKNOWN` as **text**, not the internal 2/1/0/3/-1 integers. A numerical
habit can also have numeric values: the parser intentionally rejects them rather
than guessing that 0/1/2 is a Boolean answer.

| Export state | Preview answer | Interpretation |
| --- | --- | --- |
| `YES_MANUAL` | `true` | User-recorded completion |
| `NO` | `false` | Exported explicit non-completion |
| `YES_AUTO` | `null` | Schedule satisfaction, **not** observed completion |
| `SKIP` | `null` | Not applicable; distinct from No |
| `UNKNOWN` / empty value | `null` | Unknown |
| Absent row in selected range | `null` | Unlogged, not No |

The computed export may replace an original No/unknown day with `YES_AUTO` when
the habit frequency is satisfied. Those original answers **cannot be recovered**
from this CSV. Do not use this preview for lossless round-trip synchronization.

Protocol references (read, not copied into NOOP):
- [Loop exporter at b56547f](https://github.com/kvnloo/uhabits/blob/b56547f478226a91812cac73398fa9560698e06d/uhabits-core/src/commonMain/kotlin/org/isoron/uhabits/core/io/HabitsCSVExporter.kt)
- [Named states](https://github.com/kvnloo/uhabits/blob/b56547f478226a91812cac73398fa9560698e06d/uhabits-core/src/commonMain/kotlin/org/isoron/uhabits/core/models/Entry.kt)
- [Computed-entry semantics](https://github.com/kvnloo/uhabits/blob/b56547f478226a91812cac73398fa9560698e06d/uhabits-core/src/commonMain/kotlin/org/isoron/uhabits/core/models/EntryList.kt)

Credit: Álinson Santos Xavier and Loop contributors for the source export and
checkmark model; ActivityWatch contributors for the existing telemetry foundation.
The adapter is independently implemented against that file format. It does not
copy GPL source into NOOP or change any project's license.

## Run locally

Python 3.10+ and its standard library are sufficient for both CLIs. An IANA
 timezone database must be available (the system database or Python `tzdata`).
Tests additionally require pytest. Keep exports and mapping files **outside git**.

1. Export from Loop, unzip locally, and select **one per-habit** `Checkmarks.csv`
   with the exact header `Date,Value,Notes`. Do not select root combined
   `Checkmarks.csv`, `Scores.csv`, a backup database, or a numeric habit. The CSV
   does not identify its habit type or stable ID: explicitly confirm the selected
   Boolean habit and maintain the same opaque alias across exports.
2. Save an explicit mapping locally. Replace the example factor key with the
   **exact existing NOOP Journal question**. The tool cannot verify that catalog;
   every output reports `target_catalog_verified: false`.

```json
{
  "schema": "loop-noop-preview.mapping.v1",
  "consent": "local-preview-only",
  "source_instance": "loop-phone-1",
  "habit_key": "habit-001",
  "habit_type": "boolean",
  "noop_factor_key": "Did I finish guided breathing before bed?",
  "timezone": "America/Chicago",
  "wake_day_offset": 1,
  "value_encoding": "loop-named-v1"
}
```

Select `wake_day_offset: 1` only when the selected action date should be associated
with the following wake day; choose 0 for same-day attribution. This is a user
mapping, not a detector. Date-only CSVs contain no observed event timestamp or
historical timezone: `event_timestamp_utc` stays null. For travel/timezone changes,
split imports into explicitly mapped ranges rather than inventing timestamps.

```sh
# Optional: existing ActivityWatch analysis, with corrected civil-day splitting.
python3 scripts/research_flow_metrics.py /private/activitywatch.json \
  --timezone America/Chicago --output /private/flow-proxies.json

# Preview only. No NOOP import or remote access occurs.
python3 scripts/research_loop_bridge.py /private/selected-habit/Checkmarks.csv \
  --mapping /private/loop-mapping.json \
  --from-day 2026-10-01 --through-day 2026-10-14 \
  --activity-report /private/flow-proxies.json \
  --output /private/loop-preview.json
```

Omit `--activity-report` to inspect Loop-only evidence. Existing output files and
input files are never overwritten. New report files use owner-only permissions
on platforms supporting them. No notes, habit titles from the export path,
window titles, URLs, application names or raw bucket identities enter the output.
The explicitly selected NOOP question **is** emitted; treat reports as personal
data and do not upload them to GitHub.

## Join and reimport behavior

- ActivityWatch context joins to the **action's source local day**, not the next
  wake day. `outcome_wake_day` is a separate proposed future health-outcome join.
- ActivityWatch reports must use the same timezone and declare
  `source.day_attribution: local-midnight-split-v1`. Regenerate older start-day
  reports; do not silently join them. Event windows split at local midnight,
  including 23/25-hour DST days, leap day and New Year.
- Unknown or zero observed-window coverage cannot masquerade as zero context
  switches or fragmentation. Missing measurements remain null.
- Observation IDs depend on source alias, habit alias and local day. Repeating or
  reordering an export does not mint new IDs; corrected answers retain identity
  and change their revision. File and mapping hashes preserve provenance.
- Identical duplicate-date rows collapse; conflicting duplicates abort the
  **entire** preview. No silent first/last-wins assumption.
- Numeric states, combined exports, malformed CSV/JSON, non-finite metrics,
  conflicting timezone/recipes and oversized inputs fail closed. Limits: 8 MiB
  per input, 20,000 CSV records, and 3,660 selected days.

## Verification and next gate

```sh
python3 -m pytest scripts/tests/test_research_*.py -q
```

Tests use synthetic fixtures only, including an end-to-end run of both real CLIs.
They do not establish reminder-shield efficacy, actual learning gains, a live
phone connection or NOOP database compatibility. NOOP observation/receipt drafts
remain held. Anki/FSRS outcome adapters and actual bidirectional sync are **not
implemented** by this tool.

For the paired Loop/ActivityWatch A/B, use the existing debug-only ADB lease and
content-free reminder export; measure real sessions only with user consent and
prespecified comparisons. Android ActivityWatch currently pushes its buckets but
**does not pull desktop data**, so aw-sync alone cannot deliver a desktop focus
lease to Loop. Keep transport and adaptive notification automation disabled until
that separate device/privacy gate is verified.

Official transport reference: [ActivityWatch syncing](https://docs.activitywatch.net/en/latest/syncing.html).
