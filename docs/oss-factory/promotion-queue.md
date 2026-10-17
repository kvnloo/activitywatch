# ActivityWatch — OSS promotion queue

Origin: https://github.com/ActivityWatch/activitywatch
Downstream fork: https://github.com/kvnloo/activitywatch

This is the **single project-local promotion ledger** while Issues/Discussions are disabled on this fork. It is not approval for origin publication. Original authors, PRs, reviews and evidence retain their own provenance.

## Verified promotion receipt (2026-10-16 CDT / 2026-10-17 UTC)

- [Pilot PR #103](https://github.com/kvnloo/oss-factory/pull/103) exact pushed head: [20b8d134f23a465791a6281691ff0630e0400ed8](https://github.com/kvnloo/oss-factory/commit/20b8d134f23a465791a6281691ff0630e0400ed8).
- [GitHub Actions #39004452145](https://github.com/kvnloo/oss-factory/actions/runs/39004452145): **96/96 synthetic Python tests passed**; source compilation and two-day sample generation passed; registry validated **38 unique records**.
- PR is mergeable and 0 behind factory main, but remains **LIMITED: downstream human review only**. No ActivityWatch origin PR, CI on real personal data, or default-branch merge.
- New code covers strict review-log types, app-name privacy, FSRS calibration with opt-in suppression, and explicit scheduler-day rollover. The Anki 4 AM default is a user-configurable setting; actual runtime preference must be known before interpreting a true daily join.
- Registry reconciliation preserved the previous 37 canonical project objects/topology and added ActivityWatch without deleting anyone's work. Contributor credit and existing fork draft #2 retained.

## Origin-ready
None independently verified. Do not publish an origin PR based only on synthetic fixture success.

## Existing downstream work (LIMITED)

- [OSS Factory Lane 19 pilot #103](https://github.com/kvnloo/oss-factory/pull/103): synthetic ActivityWatch current-window/AFK ↔ Anki review aggregates. Includes AFK conflict/missingness, strict JSON integer review fields, malformed-row handling and app-allowlist privacy. Human review remains necessary. Provenance: [current PR branch](https://github.com/kvnloo/oss-factory/tree/lane19/activitywatch-anki-evidence-pilot-20261014-v2). CI: [Lane 19 synthetic QA](https://github.com/kvnloo/oss-factory/actions/workflows/lane19-learning-qa.yml).
- [ActivityWatch fork draft #2](https://github.com/kvnloo/activitywatch/pull/2): privacy-preserving activity/flow **proxies**, not a validated classifier or learning benefit.
- Lane 7 methodological handoff: calibration and held-out FSRS probability evaluation require *true pre-review predictions*, provenance, chronological separation and explicit missingness.
- Lane 6 routing handoff: **affirmative opt-in** and local-only suggestions; never use screen time for mastery labels, causal conclusions or automated FSRS rescheduling.

## Requirements for any origin promotion

1. Validate a supported ActivityWatch user requirement independent of synthetic tests, and confirm no existing maintainer work covers it.
2. Recheck reviewer feedback, exact current head, CI, privacy/consent and licenses.
3. Preserve contributor credit (ActivityWatch: Erik and Johan Bjäreholt and contributors; Anki: Damien Elmes and contributors; FSRS: open-spaced-repetition contributors; MemoryOS: BAI-LAB; NeuroForge contributors; Lane 19 pilot and tests: Zer0 OSS Factory).
4. Record explicit scoped human approval before origin-facing writes; origin maintainers decide default-branch merges.

No personally identifiable usage/learning data or raw timestamps/URLs/card IDs belong here. Synthetic review-button pass rate is **not independently measured mastery or causal learning effect**.

Legacy factory issue: https://github.com/kvnloo/oss-factory/issues/179 (historical redirect only).

## QA receipt — 2026-10-17 (Lane 19)

- [Existing pilot PR #103](https://github.com/kvnloo/oss-factory/pull/103) exact head [`0ed9791cba20f387c1930ae7766fdd3a8eeed0cf`](https://github.com/kvnloo/oss-factory/commit/0ed9791cba20f387c1930ae7766fdd3a8eeed0cf), [hosted CI #39014103407](https://github.com/kvnloo/oss-factory/actions/runs/39014103407): **103/103 Python tests passed** (7 new synthetic-only tests, including 800 deterministic perturbations). Head was **0 behind main**, mergeable and without reviews/comments at this receipt's preflight.
- Correctness: conflicting held-out Anki review IDs now suppress aggregate FSRS Brier/calibration metrics, avoiding potentially selection-biased scores. This is fixture-level contract evidence, **not** verified learner benefit, true FSRS prediction provenance, independently demonstrated mastery or a user-facing ActivityWatch requirement.
- **LIMITED / human review only.** No personal telemetry, origin-facing ActivityWatch write, or default-branch merge. Retain [ActivityWatch fork draft #2](https://github.com/kvnloo/activitywatch/pull/2) and earlier code/author receipts as separate sources.
- **Lane 7:** self-reported review-button recall is not independently measured mastery; declared pre-review timestamps and training cutoffs do not establish genuine prediction provenance or leakage-free fitting; unknown/malformed denominators stay unknown.
- **Lane 6:** suggest opt-in, local-only aggregate exploration only; never infer a causal benefit from screen time or change FSRS scheduling. Affirmative consent is required for real inputs.
- **Credit:** Erik and Johan Bjäreholt/ActivityWatch contributors; Damien Elmes/Anki contributors; open-spaced-repetition FSRS contributors; BAI-LAB MemoryOS and NeuroForge contributors; synthetic contract/QA by Zer0 OSS Factory Lane 19. Preserve original licenses.

## Downstream QA receipt — 2026-10-17 (Lane 19, exact-head update)

- Existing [factory PR #103](https://github.com/kvnloo/oss-factory/pull/103) advanced **without new PR or main merge** to [62ce5857a2f8084a3961385a2ba278de2e09895f](https://github.com/kvnloo/oss-factory/commit/62ce5857a2f8084a3961385a2ba278de2e09895f). Branch **0 behind main**; no reviews at verification.
- Exact-head [hosted CI #39049544001](https://github.com/kvnloo/oss-factory/actions/runs/39049544001) **SUCCESS: 113/113 synthetic Python tests**; two-day fixture/registry checks green. New work guards oversized FSRS probability values and duplicate signatures; adds a metadata-only nonpublic report projection and 10 adversarial tests.
- **LIMITED; not origin-ready.** The privacy projection is optional caller-enforced routing, **not anonymization or a security boundary**; the local opt-in evaluation can still expose calibration cell counts/fractions if leaked without the projection. Separate privacy review, authentic prediction provenance, independent user need, and explicit bounded origin approval remain missing.
- **Lane 7 evaluation contract:** review-button pass is self-reported recall; prediction chronology/model-fit cutoffs remain declared and cannot prove independent mastery or learning gains. **Lane 6:** affirmative opt-in/local-only routing; do not infer causality from screen time or modify FSRS scheduling.
- No identifiable learner telemetry, upstream GitHub writes, or default-branch merges. Original ActivityWatch/Anki/FSRS, BAI-LAB MemoryOS and NeuroForge contributors remain credited; synthetic QA by Zer0 OSS Factory Lane 19.
