# `spark-profiler`

A lightweight PySpark observability library that captures structured job metrics as a side effect of normal code and explains them in plain English on demand.

## Problem

Data scientists write PySpark jobs, the jobs are slow or expensive or OOM in production, and the debugging loop is brutal: open the Spark UI, squint at the DAG, guess at the bottleneck, try a fix, wait twenty minutes, repeat. The Spark UI is a forensic tool — it tells you what happened but not what to do about it. Most data scientists never develop deep Spark intuition because the feedback is too slow and too cryptic, and the expertise needed to translate raw metrics into action lives in a handful of people on the platform team.

The result is a constant tax: failed jobs that should have been caught locally, expensive jobs that run for months before anyone notices, and Slack pings to the platform team for problems that are structurally the same as ones they've debugged a dozen times before.

## Opportunity

Spark already emits everything needed via `SparkListener`. Skew, shuffle sizes, spill, broadcast decisions, stage durations — it's all there as structured events. The gap is twofold: nobody captures it in a usable form for Python users, and even when captured, raw metrics don't translate to action without expertise. A small library can close both gaps: capture the events as structured Python objects, run a deterministic rules engine to flag known anti-patterns, and use Claude as an explanation layer on top of the structured findings.

## Design philosophy

**Deterministic core, AI on the edges.** The library's correctness does not depend on AI. The rules engine finds problems; Claude explains them. If the AI layer is unavailable, slow, or wrong, the structured profile and the rules-based findings are still useful on their own.

**One line to enable, zero lines to use.** Instrumentation should feel like turning on a flag, not learning a new framework. Data scientists already write PySpark the way they write it; the library meets them there.

**Composable with the existing platform.** Profile events flow into `inference-logger` as a new event type so model performance, inference logs, and pipeline performance all live in one observability stack.

## API

Three entry points, each appropriate for a different context.

### Interactive (context manager)

```python
from spark_profiler import profile

with profile() as p:
    df = spark.read.parquet("s3://...")
    result = df.groupBy("user_id").agg(...).collect()

p.explain()   # plain-English narrative of the job
p.suggest()   # ranked optimization suggestions with code examples
p.report()    # full structured report (markdown or JSON)
```

### Component-level (decorator)

```python
@profile.component
def train_features(spark, input_path):
    ...
```

Every component execution produces a profile artifact logged alongside KFP outputs.

### Production (always-on)

```python
profile.attach(spark, sink="inference-logger")
```

Continuous profiling for long-running pipelines, sampled at the stage level with bounded overhead.

## Architecture

Three layers, each independently useful.

### Layer 1 — Collection

A `SparkListener` subclass hooks into `onStageCompleted`, `onTaskEnd`, `onJobEnd`, and related events via py4j, writing structured events to an in-memory buffer.

Captured per stage: input and output bytes, shuffle read and write, spill, task duration distribution (p50/p95/p99/max), executor memory peak, GC time, and the logical and physical plan for the stage's query when available. Captured per task: the skew indicators — particularly the ratio of max-to-median task duration, which is the single most useful skew signal.

This layer contains no AI and is useful on its own. Exposing the structured data as a Pandas DataFrame would already be valuable for data scientists who want to analyze their own jobs.

### Layer 2 — Diagnosis

A rules engine over the collected data that flags known anti-patterns deterministically. Each rule is a small pure function returning a typed `Finding` with a severity level.

Representative rules:

- max-task-duration divided by median-task-duration exceeds 10 — indicates skew
- shuffle read exceeds 5x input read — indicates over-shuffling
- any spill greater than zero — indicates memory pressure
- broadcast threshold exceeded but no broadcast hint present — missed broadcast opportunity
- stage with a single task — accidental coalesce or non-parallel operation

These rules are cheap, fast, and do not require Claude. They produce structured findings that drive the explanation layer.

### Layer 3 — Explanation

The AI layer. Takes the structured profile, the rules-engine findings, and optionally the query plan, then produces a plain-English narrative of what the job did and where time went, plus a ranked list of suggested fixes with code examples.

The Claude call is bounded by construction. It sees metrics and plans, never data. Table and column names are redacted before the prompt is built, so explanations reference "the join key" or "the larger table" rather than leaking identifiers. Input and output are structured, so the AI layer is essentially a prompt + schema rather than an open-ended agent.

Crucially, Claude is not finding the problems — the rules engine already found them. Claude is explaining and ranking them and generating fix suggestions. This is dramatically more reliable than asking an LLM to analyze raw metrics from scratch.

## Package layout

A single Python package, roughly 800 to 1200 lines for v1.

```
spark_profiler/
├── listener.py      SparkListener subclass, py4j boilerplate, event capture
├── profile.py       Public API — context manager, decorator, attach()
├── metrics.py       Typed dataclasses for stages, tasks, jobs, full profile
├── rules.py         Rules engine, each rule a small function returning Finding
├── explain.py       Claude integration — prompt construction, structured output
├── report.py        Markdown and JSON renderers
└── redact.py        Identifier redaction for plans before they leave the process
```

Tests are primarily snapshot tests over recorded profiles. A handful of real Spark jobs exhibiting each anti-pattern (skewed join, missed broadcast, over-shuffling, spill) are captured once as JSON fixtures, and the test suite runs the rules engine and report generator against them. The AI layer is tested for structural properties (suggestions list is non-empty for known anti-patterns, confidence is calibrated) rather than exact text, because LLM output is non-deterministic.

## Sharp edges

**Cluster mode.** A `SparkListener` runs on the driver, which means executor-internal detail is not visible without additional instrumentation. v1 should be explicit about this — "driver-side metrics only" — and not pretend to be a full APM.

**Overhead in always-on mode.** Continuous profiling has cost. Always-on mode is opt-in per pipeline and samples at the stage level rather than the task level in production.

**Plan capture sensitivity.** Logical and physical plans are large and contain table and column names that may be sensitive. Redaction before the Claude call is mandatory, not optional. The `redact.py` module handles this and is tested independently.

**The skew rule is most of the value.** If the library only ever caught skew and explained it well, it would still be hugely valuable. Scope creep toward exotic rules should not delay shipping the core.

## Integration with the existing platform

`spark-profiler` emits structured events. `inference-logger` already exists as the team's unified observability layer. The natural integration is treating profile events as a new event type in inference-logger's schema, so a single query can answer "which of my model's batches had slow pipelines, and which slow pipelines had drift in the predictions they produced." That is a real platform story rather than another standalone tool.

`spark-profiler` also pairs naturally with `kubekit` — the decorator form of the API can be auto-applied to every KFP component by a kubekit helper, so profiling is zero-effort for any team using kubekit.

## What v1 ships

- `SparkListener` collection layer producing typed stage and task metrics
- Rules engine with the five high-value rules above, plus a plugin interface for adding more
- Markdown and JSON report renderers
- Claude-powered `explain()` and `suggest()` methods
- Identifier redaction
- Snapshot tests over recorded profiles for each rule
- `inference-logger` sink adapter
- Documentation with one worked example per rule

What v1 explicitly does not ship: executor-internal instrumentation, a web UI, historical trend analysis across runs, cost attribution. Each of those is a reasonable v2 direction; none of them are prerequisites for the library to be valuable.

## Success criteria

Within one quarter of shipping: every KFP component using kubekit profiles automatically, at least one major optimization lands on a production pipeline driven by a `suggest()` output, and the volume of "why is my Spark job slow" Slack messages measurably drops. Within two quarters: the rules engine has been extended by someone other than the original author, which is the signal that the library has become substrate rather than a personal project.
