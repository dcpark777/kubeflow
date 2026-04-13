# CLAUDE.md

This file is read automatically by Claude Code when working in this repo. It is a short pointer to the full handoff document.

## Start here

**Read `HANDOFF.md` before making any changes.** It contains the design philosophy, current state, known gaps, and rules for how to extend the package safely. Skimming it is cheap; skipping it will lead to proposing changes that contradict decisions already made.

## Quick facts

- **What this is**: A Jupyter magics package (`kubekit-jupyter`) that makes authoring KFP v2 pipelines pleasant for data scientists new to KFP, with a decompiler that bridges notebook work to production repos.
- **Philosophy**: Deterministic core, AI on the edges. Fail closed. Legible output. Meet users where they are.
- **Current status**: v1 with 38 passing tests, pilot-ready but not yet piloted.
- **The thing you must not break**: `test_component_template_passes_validation` — scaffolded component templates pass validation on first run. This is the "new user sees a green checkmark on shift-enter" invariant.

## Commands

```bash
pip install -e ".[dev]"   # install with test deps
pytest -q                  # run the suite (should pass in ~200ms)
```

## Before you change anything

1. Run `pytest -q` and confirm it's green
2. Read the relevant section of `HANDOFF.md`
3. Ask yourself whether the change respects the 8 design principles in the philosophy section
4. If you're adding a rule or template, add a test for it in the same commit
5. If you're adding anything AI-powered, confirm there's a deterministic fallback

## Companion documents in this bundle

- `HANDOFF.md` — full brief (read this first)
- `platform-library-ideas.md` — catalog of ~40 library ideas this package composes with
- `spark-profiler-concept.md` — detailed concept doc for one of the ideas, showing the pattern to follow
