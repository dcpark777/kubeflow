# Task agents

A layered architecture for turning user task descriptions into
high-quality agent executions.

## Pipeline

```
User submits task
    ↓
[decomposer]  → single / compound / unclear
    ↓ (for each sub-task if compound)
[classifier]  → task label (planning/brainstorming/coding/research/unclear)
    ↓
[selector]    → model tier + thinking (haiku/sonnet/opus × off/adaptive/high)
    ↓
[profile]     → behavior config injected into system prompt
    ↓
[memory]      → load prior state, inject as context
    ↓
=== EXECUTE (your app launches Claude Code here) ===
    ↓
[critique]    → pass / revise, with guidance (high-stakes tasks only)
    ↓ (if revise)
=== REVISION PASS ===
    ↓
[memory]      → extract structured state, append to task memory
    ↓
Deliver output to user
```

`example_pipeline.py` has the whole flow.

## Components

### Decomposer (`decomposer/`)

Detects whether the user's request is actually multiple tasks. Splits
cohesive compound requests (e.g., "research X, then plan the migration
based on what you find") into separately-routed sub-tasks with explicit
dependencies. Returns `unclear` when genuinely ambiguous.

Haiku-based. Sub-tasks run as independent pipelines; dependencies
mean the dispatcher sequences them and injects earlier outputs into
later tasks' context.

### Classifier (`classifier/`)

Identifies the task type: `planning`, `brainstorming`, `coding`,
`research`, or `unclear`. Haiku-based. Returns `unclear` with candidate
labels when torn; app asks the user to pick.

### Selector (`model-selector/`)

Picks the model tier and thinking mode. Haiku-based — selection is
routing, not reasoning. Adaptive thinking is the default on Sonnet/Opus
(those models self-tune); `high` is a deliberate override.

### Profiles (`profiles/`)

Mode configs injected into the system prompt. One per task type ×
(execute, refine). Ship with: planning, brainstorming, coding. Research
profiles aren't authored yet.

### Memory (`memory/`)

Per-task state directory. Each task gets:

```
tasks/<task_id>/
  ├── task.md           # Task description (evolves with refinement)
  ├── state.md          # Current state: status, findings, open questions
  ├── history.md        # Append-only log of runs
  ├── refine_log.md     # Append-only log of refinement turns
  └── artifacts/        # Files produced by runs
```

`state.md` gets rendered into the system prompt at the start of each
run, so agents build on prior work instead of starting from scratch.
After each run, a Haiku extractor parses the output into structured
state fields and appends them.

### Critique (`critique/`)

After high-stakes executions (Opus-tier, or planning/research at
Sonnet-tier), a Sonnet reviewer reads the output against the task
description and either passes it or returns specific revision
guidance. If revise, the dispatcher runs one revision pass — not a
loop.

Not every task gets critiqued. Haiku-tier tasks, brainstorming, and
Sonnet-tier coding skip it: the cost/latency isn't justified and
critique on low-stakes outputs often finds noise rather than real
issues.

### Skills (`skills/`)

Procedural moves Claude loads mid-execution when a specific procedure
applies. Drop into `~/.claude/skills/` or project-local skills dir.
Ship with:

- `task-refinement` — sharpen any task
- `plan-decomposition` — turn a goal into an actionable plan

## How they compose

```
User: "Research vector DB options, pick one, and write a migration plan"
  ↓
decompose → compound, 2 subtasks
  ↓
  subtask 0: "Research vector databases..."
    classify → research
    select   → sonnet / adaptive
    memory   → fresh
    execute  → [output]
    critique → pass
    memory   → state updated
  ↓
  subtask 1: "Given the recommended DB, write a migration plan"
    context  → subtask 0's output injected
    classify → planning
    select   → opus / adaptive
    memory   → fresh
    execute  → [output]
    critique → revise: "add rollback strategy"
    revise   → [revised output]
    memory   → state updated
  ↓
User sees both outputs with the pipeline's provenance
```

## Design principles

**Each layer owns one decision.** Decomposer decides shape, classifier
decides type, selector decides size, profile decides behavior, memory
decides context, critique decides quality gate. Changing any one
doesn't cascade.

**Cheap routing, expensive execution.** All routing-layer calls
(decomposer, classifier, selector, extractor) use Haiku. The critique
pass uses Sonnet. The main execution uses whatever the selector picked.
Total routing overhead is under a cent per task.

**Fail-safe parsing.** Every router returns a safe default on malformed
output. Selection failures route to Sonnet/adaptive. Critique failures
return pass. Classification failures return unclear (which asks the
user, so it's self-healing).

**Markdown, not JSON, for human-adjacent files.** Task state, profiles,
and skills are all markdown. Agents read markdown better, and users can
inspect or edit by hand when debugging.

## What's NOT here

- **Research profiles** — classifier knows the label; profiles not
  authored
- **A dispatcher / executor** — the thing that actually launches Claude
  Code. This depends on your app's infra (sync vs async, UI, streaming)
  so it's left to you
- **Cost caps / budget enforcement** — the selector picks tiers but
  doesn't know your budget
- **Per-user learning** — no feedback loop from thumbs up/down back
  into prompts
- **Parallel sub-task execution** — the compound pipeline sequences
  sub-tasks respecting dependencies, but doesn't run independent ones
  in parallel. Your dispatcher decides this
- **Caching** — classifier and selector calls aren't cached. If your
  users create many similar tasks, add a hash-keyed cache layer

## Stress tests worth running

- **Decomposer false-positive rate** — you don't want "migrate our
  pipelines" getting split into six sub-tasks. Test against real user
  tasks and tune the prompt's "what is NOT compound" section
- **Critique noise rate** — if critique returns revise too often,
  users will learn to ignore it. If it returns pass too often, it's
  not earning its cost. Target feels like ~20% revise rate on the
  tasks that get critiqued
- **Memory relevance** — does injecting prior state actually improve
  later runs, or does it distract the agent? Worth comparing fresh
  runs vs memory-enabled runs on the same iterated task
