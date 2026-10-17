# ActivityWatch — OSS promotion queue

Origin: https://github.com/ActivityWatch/activitywatch
Downstream fork: https://github.com/kvnloo/activitywatch

This is the **single project-local promotion ledger** while Issues/Discussions are disabled on this fork. It is not approval for origin publication. Original authors, PRs, reviews and evidence retain their own provenance.

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
