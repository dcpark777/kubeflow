# Task agents — handoff package

This tarball contains everything needed to implement the task-agents
layered pipeline in your app.

## Contents

```
task-agents-handoff/
├── README.md                # this file
├── implementation-docs/     # the plan for Claude Code to build from
│   ├── 00-orchestrator.md   # entry point — read this first
│   ├── 01-data-model.md
│   ├── 02-core-pipeline.md
│   ├── 03-routing-layers.md
│   ├── 04-profiles-and-skills.md
│   ├── 05-memory.md
│   ├── 06-critique.md
│   └── 07-integration-and-testing.md
└── reference-drafts/        # v0.1 working implementations of each piece
    ├── README.md
    ├── example_pipeline.py
    ├── classifier/
    ├── decomposer/
    ├── memory/
    ├── critique/
    ├── model-selector/
    ├── profiles/            # 6 profile .md files
    └── skills/              # 2 skill SKILL.md files
```

## How to use this with Claude Code

1. **Drop the whole directory into your repo** (or a sibling directory
   Claude Code can read).
2. **Point Claude Code at this package** and tell it to start with
   `implementation-docs/00-orchestrator.md`.
3. **The orchestrator tells Claude Code what to build and in what
   order.** It references the numbered docs in sequence; each doc
   owns one layer.
4. **The reference drafts show the shape** of prompts, types, and
   logic. Claude Code reads them when it needs concrete starting
   points. When the plan docs and drafts conflict, the plan docs win
   (this is stated in `00-orchestrator.md`).

## A suggested kickoff prompt for Claude Code

```
Read task-agents-handoff/implementation-docs/00-orchestrator.md and
then work through the numbered docs in the order it specifies. The
reference-drafts/ directory contains v0.1 implementations you can
pull from for shape — treat them as starting points, not final code.
The plan docs describe the target design; where they differ from the
drafts, the plan docs win.

Before you start implementing, read the existing app code to
understand how tasks are currently dispatched, and tell me what you
see so we can align on integration points before you touch anything.
Don't start writing code until we've agreed on the integration shape.
```

That last paragraph matters. The integration doc assumes a particular
shape of dispatcher; if your app's dispatcher differs, Claude Code
should surface that before writing anything.

## What's NOT included

- **The existing app code.** This package is additive — it adds a
  `task_agents/` module your app imports. Your app owns everything
  else (HTTP, UI, persistence, Claude Code spawning).
- **Research profiles.** The classifier knows about the `research`
  label, but `research-execute.md` and `research-refine.md` aren't
  drafted. `04-profiles-and-skills.md` has guidance on authoring
  them.
- **A finished test suite.** The docs specify what to test and what
  targets to hit; actual test authoring is part of the build.

## Scope reminder

This is a layered pipeline for routing + execution + quality gates.
It is NOT:

- A new chat UI
- A replacement for your Claude Code dispatcher
- A multi-user permissions system
- A cross-task search index
- A budget/cost enforcement layer

Each of those is a reasonable future addition; none of them are in
this package.

## Build order

1. Data model (types)
2. Profiles and skills (content files)
3. Routing layers (decomposer, classifier, selector)
4. Memory (state directory + extractor)
5. Critique (gate + revision prompt)
6. Core pipeline (composes everything)
7. Integration (wire into existing app + stress tests)

Full details in `implementation-docs/00-orchestrator.md`.
