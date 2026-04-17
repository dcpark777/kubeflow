# Task agents: implementation plan

Read this file first. It tells you what to build, how the pieces
relate, and the order to build them in. The numbered files are the
specs for each piece.

## What you're building

The app takes user-submitted tasks and runs them through Claude.
Today, every task goes through the same prompt shape and model
settings. You are adding a layered pipeline that:

1. **Decomposes** compound requests into independent sub-tasks
2. **Classifies** each task as planning / brainstorming / coding /
   research
3. **Selects** the right model tier and thinking mode per task
4. **Injects a profile** (behavior config) into the system prompt
   based on task type and mode (execute vs. refine)
5. **Loads per-task memory** so iterative runs build on prior work
6. **Executes** via Claude Code with all of the above composed
7. **Critiques** high-stakes outputs and runs one revision pass if
   the reviewer flags real issues
8. **Writes structured state** back to task memory

Each layer is a separate concern. Each makes one decision. Changing
one shouldn't cascade.

## Order of operations

Build in this order. Each step unblocks the next:

1. **Data model** (`01-data-model.md`) — types and enums. Everything
   else imports from here.
2. **Profiles and skills** (`04-profiles-and-skills.md`) — content
   files. No code dependencies; fine to drop in early so they exist
   when the pipeline references them.
3. **Routing layers** (`03-routing-layers.md`) — decomposer,
   classifier, selector. Three parallel implementations of the same
   shape (markdown prompt + Haiku call + fail-safe parse).
4. **Memory** (`05-memory.md`) — task state directory + extractor.
5. **Critique** (`06-critique.md`) — gate + revision prompt builder.
6. **Core pipeline** (`02-core-pipeline.md`) — the orchestration that
   composes everything. Build this last; it's the top of the stack.
7. **Integration and testing** (`07-integration-and-testing.md`) —
   wire into the existing app, run stress tests.

## Reference drafts

The author of this plan has reference drafts for most of the
components in a separate directory (likely provided alongside these
docs). The reference drafts include:

- All prompt `.md` files (classifier, decomposer, selector, critique,
  extractor) with worked examples
- Profile drafts for planning, brainstorming, and coding (both modes)
- Skill drafts for task-refinement and plan-decomposition
- Python implementations of each module

Use these as starting points for the shape of each file. They reflect
the style and conventions the author wants, and the prompts in
particular have been through some iteration. Don't treat them as
final — they're v0.1 — but they're a much better starting point than
an empty file.

The plan docs describe what each component should do; the reference
drafts show one valid way to implement it. When they differ, the
plan docs win. Ask the user if you're unsure.

## Design principles (non-negotiable)

These shaped every decision below. When in doubt, fall back to these:

- **Each layer owns one decision.** Don't merge decomposer and
  classifier just because both are "classifying things." Don't let
  profiles do memory management. Separate concerns is the whole
  point.
- **Cheap routing, expensive execution.** All routing calls
  (decomposer, classifier, selector, extractor) use Haiku. Critique
  uses Sonnet. Main execution uses whatever the selector picked.
  Total routing overhead should be under 2 seconds and under a cent
  per task.
- **Fail-safe parsing.** Every router that calls an LLM must handle
  malformed output gracefully with a safe default — never raise into
  the main pipeline. Selection failures route to Sonnet/adaptive.
  Critique failures return pass. Classification failures return
  unclear (which self-heals by asking the user).
- **Markdown, not JSON, for human-adjacent files.** Task state,
  profiles, skills are all markdown. Agents read markdown better.
  Users can inspect and edit by hand when debugging.
- **Prompts live in their own `.md` files, not as Python strings.**
  Every LLM-call module has a sibling `prompt.md` that is loaded at
  runtime. Iterating on behavior should not require editing Python.

## Architectural shape

```
task description
    │
    ▼
┌─────────────┐   compound?     ┌──────────────┐
│ decomposer  │ ─────yes────▶   │ split into   │
│   (Haiku)   │                 │  subtasks    │
└─────────────┘                 └──────┬───────┘
       │                               │
       │ single                        │ (for each subtask,
       │                               │  respecting deps)
       ▼                               ▼
┌─────────────┐                ┌─────────────┐
│ classifier  │◀───────────────│  pipeline   │
│  (Haiku)    │                │ (recursive) │
└──────┬──────┘                └─────────────┘
       │ label
       ▼
┌─────────────┐
│  selector   │
│  (Haiku)    │
└──────┬──────┘
       │ tier + thinking
       ▼
┌─────────────┐
│  profile    │   resolve label + mode → .md file
│ (filesystem)│
└──────┬──────┘
       │ system prompt addition
       ▼
┌─────────────┐
│   memory    │   load prior state if task exists
│ (filesystem)│
└──────┬──────┘
       │ memory context
       ▼
┌═════════════┐
│  EXECUTE    │   launch Claude Code (app runner owns this)
└═════════════┘
       │ output
       ▼
┌─────────────┐
│  critique   │   only if selector_tier is opus,
│  (Sonnet)   │   or (sonnet AND label is planning/research)
└──────┬──────┘
       │ verdict
       ├── pass ──────────────────────────────┐
       │                                       │
       │ revise                                │
       ▼                                       │
┌═════════════┐                                │
│  REVISION   │   one pass, not a loop         │
└══════╦══════┘                                │
       │                                       │
       └──────────┬────────────────────────────┘
                  ▼
           ┌─────────────┐
           │  extractor  │   parse output into structured state
           │   (Haiku)   │
           └──────┬──────┘
                  ▼
           ┌─────────────┐
           │  memory     │   append state; update history
           │ (filesystem)│
           └──────┬──────┘
                  ▼
            deliver to user
```

## What the existing app owns vs. what this adds

**Existing app owns** (do not touch unless explicitly required):

- The HTTP / UI surface for creating, viewing, and managing tasks
- The Claude Code dispatcher (the process that actually spawns
  Claude Code sessions and captures output)
- User authentication, task persistence, and any multi-user concerns
- The refinement chat UI (this code adds content to those prompts;
  it doesn't own the chat mechanics)

**This code adds**:

- A `task_agents/` Python package (or equivalent module) that
  exposes a clean API the existing app imports
- Per-task memory state directories under a configurable root
- Markdown content files (profiles, skills, prompts) in the package

The dispatcher should continue doing what it does — but instead of
calling Claude Code with a generic system prompt, it calls
`task_agents.prepare_task_for_execution(...)` first, gets back a
payload with the computed args + profile content + memory context,
and passes those to Claude Code. After execution, it calls
`task_agents.finalize_execution(...)` which handles critique, revision
dispatch (which calls back into the executor), and memory updates.

## Conventions

- Python 3.10+. Use `from __future__ import annotations` and
  `dataclass(frozen=True)` for result types.
- `Literal` types for enums (labels, tiers, thinking, modes).
- Every LLM-calling function accepts an optional `client: Anthropic`
  parameter so tests can inject. Defaults to `Anthropic()`.
- Model IDs: use dated IDs in code (`claude-haiku-4-5-20251001`).
  The selector has a map from tier aliases to dated IDs — that's
  the one place to update when bumping models.
- Logging: emit a structured log line per routing decision with
  `{stage, input_hash, decision, latency_ms, tokens}`. The app's
  existing observability picks these up.
- Imports: no cross-module dependencies between routing layers.
  Each routing module is independently importable and testable.

## Testing expectations

Each routing layer (decomposer, classifier, selector) ships with a
`test_*.py` that runs realistic cases and reports pass/fail. These
aren't unit tests in the traditional sense — they're eval harnesses
that call the real LLM. Expect flakiness on the margins. For
borderline cases, accept a band of correct answers rather than one
exact label.

For memory: unit-test the filesystem layer with `tempfile.TemporaryDirectory`.
Don't mock the LLM extractor; test it end-to-end with a short
sample output.

For critique: ship with a small eval set of (task, output) pairs
where we have opinions about pass vs. revise.

## When you're done

The app should be able to:

1. Receive a user task, detect if compound, split it if so
2. Route each (sub)task to the right profile and model
3. Execute it via Claude Code with memory context
4. Critique high-stakes outputs and revise if needed
5. Persist structured state so the next run on the same task
   builds on what's already been done
6. Handle refine-mode conversations and update task state from them

Run the end-to-end test in `07-integration-and-testing.md` to verify.
