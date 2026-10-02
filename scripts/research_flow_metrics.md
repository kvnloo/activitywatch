# Flow-state telemetry experiment v0

Status: downstream research experiment. **Not a flow detector and not a health/medical inference system.**

## Question

Can low-content ActivityWatch telemetry predict moments that a user later describes as being in flow, while remaining useful enough to study interruption and recovery?

The first experiment intentionally uses only:

- timestamps and durations,
- current-window application identity (or a user-defined context group),
- AFK / not-AFK state.

It ignores:

- window titles,
- URLs,
- screenshots,
- OCR,
- keystrokes,
- document/message contents.

The implementation is `scripts/research_flow_metrics.py`.

## Why these signals

Prior HCI field work measured task switching, interruption, suspension, and resumption from application/window activity. That supports using computer activity as a **behavioral proxy for fragmentation and recovery**, but not as proof of subjective flow.

Recent diary work relating multitasking to flow uses time-allocation fragmentation measures such as Simpson's diversity index alongside **self-reported flow**. This experiment follows that separation: telemetry measures behavior; self-report supplies the flow label.

## Metrics

### Active time

AFK events with `status=not-afk`. Window events are clipped to those intervals.

### Context switch rate

Number of transitions between adjacent app/context segments divided by active hours.

Raw application switching is imperfect: a coding task can legitimately alternate between an editor, terminal, browser docs, and a debugger. Pass a context map to group those apps into one task context:

```json
{
  "Visual Studio Code": "coding",
  "kitty": "coding",
  "Google Chrome": "coding"
}
```

Context maps should be user-defined for the experiment; inferring them from titles/content would weaken the privacy boundary.

### Fragmentation

`1 - sum(p_i^2)`, where `p_i` is the share of observed active time in context `i`.

This is Simpson diversity applied to context-time allocation. Lower values indicate more concentrated time allocation; higher values indicate more fragmentation. It is **not** a flow score.

### Sustained context blocks

Continuous active time in one app/context above a configurable duration (20 minutes by default).

The threshold is only an experiment parameter. It should not be presented as a scientific definition of deep work or flow.

### Return-to-context latency

After leaving context A, time until the first return to A within a configurable horizon (30 minutes by default), without crossing an AFK session boundary.

This is a computer-activity **resumption proxy**. It does not establish whether the switch was an external interruption, self-interruption, or intentional task transition.

## Validation protocol

### Phase A — passive baseline

Run the metrics for 7–14 ordinary workdays without changing notifications or behavior.

Primary outputs per day:

- active time,
- switches / active hour,
- fragmentation,
- median context dwell,
- sustained-context time,
- longest sustained block,
- return-to-context count,
- median return latency.

Do not optimize against these yet. First learn their natural within-person variance.

### Phase B — momentary flow labels

Pair passive telemetry with brief self-report prompts.

Recommended first version:

- 3 prompts/day at semi-random times during active work;
- never prompt during AFK;
- record the answer timestamp so telemetry can be summarized for the preceding 15/30/60 minutes;
- use a short validated work-flow measure rather than inventing a "productivity" label.

A useful candidate is the 3-item Short Flow in Work Scale (SFWS). Keep the survey response in a separate study dataset; ActivityWatch need not store it in the window bucket.

### Phase C — learn within-person predictors

For each prompt, derive telemetry features over the preceding windows:

- switch rate,
- fragmentation,
- dominant-context share,
- sustained-context duration,
- recent AFK return,
- previous interruption-like return latency,
- time of day.

Start with transparent within-person statistics before ML:

1. compare high-flow vs low-flow self-reports;
2. bootstrap confidence intervals;
3. leave-one-day-out validation;
4. check whether adding app identity materially improves prediction over timing-only features.

The goal is **not** a universal flow classifier. The interesting question is whether a small, privacy-preserving signal set can predict one person's own reports better than trivial baselines.

## Intervention experiments

Only after Phase B/C shows predictive signal.

### Experiment 1 — notification shielding

Hypothesis:

> Delaying nonurgent reminders during a high-probability focus block reduces fragmentation without increasing missed obligations.

Measure:

- interruption/context-switch rate,
- sustained-context duration,
- resumption latency,
- self-reported flow,
- reminders delayed,
- reminders missed/acted on late.

This can connect ActivityWatch with Loop Habit Tracker without requiring either project to infer mental state.

### Experiment 2 — resumption packet

Hypothesis:

> After an interruption, showing a tiny context cue reduces time-to-resumption.

Candidate cue:

- task/context name,
- previous active app set,
- elapsed interruption time,
- optionally a user-written "next step."

Do **not** include raw titles/content by default.

### Experiment 3 — recovery timing

Use Medito or another recovery tool only at natural boundaries:

- after a long focus block,
- after repeated fragmentation,
- during a voluntary break.

Compare against fixed-time prompts. Avoid interrupting the very state the intervention is intended to protect.

## Loop focus-shield intervention analysis

The companion Loop experiment emits content-free reminder records:

```text
observedEpochMillis,reminderTime,deferredUntil,shieldedFlag,...
```

Save the `FlowShieldExperiment` logcat report to a text file, then join it to an ActivityWatch export:

```sh
python3 scripts/research_flow_intervention_analysis.py \
  /path/to/activitywatch-export.json \
  /path/to/loop-focus-shield-log.txt \
  --output focus-shield-analysis.json
```

The analyzer creates event-centered windows for every eligible reminder:

- 10 minutes before;
- 2 minutes after;
- 10 minutes after;
- 30 minutes after.

It reports, by control/shield condition:

- context switch within two minutes, including a switch exactly at the reminder boundary;
- whether the same context survived across the reminder boundary;
- post-reminder switch counts;
- post-reminder return-to-context latency;
- the underlying privacy-preserving flow-proxy metrics for each window.

No habit identity or raw app/context name is emitted.

This is the first causal experiment in the flow program: **change one interruption mechanism, measure the behavioral consequence, and do not automate the detector until the intervention demonstrates value.**

## Falsifiers

This research direction should be weakened or dropped if:

- passive features do not predict self-reported flow above time-of-day / active-time baselines;
- useful prediction requires raw titles, URLs, screenshots, or similarly invasive content;
- context grouping requires so much manual maintenance that the system is not practical;
- interventions increase interruption burden or notification fatigue;
- "better" telemetry metrics fail to correspond to subjective flow or task outcomes.

## Running the v0 tool

Export ActivityWatch data to JSON, then:

```sh
python3 scripts/research_flow_metrics.py /path/to/activitywatch-export.json \
  --timezone America/Chicago \
  --output flow-proxies.json
```

With user-defined context groups:

```sh
python3 scripts/research_flow_metrics.py /path/to/activitywatch-export.json \
  --timezone America/Chicago \
  --context-map contexts.json \
  --output flow-proxies.json
```

The report contains aggregates only and never emits raw application/context names.

## References

- Czerwinski, Horvitz & Wilhite (2004), *A Diary Study of Task Switching and Interruptions*, CHI.
- Iqbal & Horvitz (2007), *Disruption and Recovery of Computing Tasks: Field Study, Analysis, and Directions*, CHI.
- DeLine & Parnin (2010), *Evaluating Cues for Resuming Interrupted Programming Tasks*, CHI.
- Moneta (2017), *Validation of the Short Flow in Work Scale (SFWS)*, Personality and Individual Differences.
- *Why and when does multitasking impair flow and subjective performance?* (2024), Frontiers in Psychology.
- *Using mental contrasting to promote flow experiences at work: A just-in-time adaptive intervention* (2024), Computers in Human Behavior Reports.
