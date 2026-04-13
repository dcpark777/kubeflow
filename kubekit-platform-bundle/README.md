# Platform Tooling Bundle

Everything built in one session of designing AI tooling for the ML platform team. This bundle is self-contained — start with `HANDOFF.md` (inside `kubekit-jupyter/`) for the authoritative brief.

## Contents

### Working code

**`kubekit-jupyter/`** — A Jupyter magics package that makes KFP v2 pipeline authoring pleasant for data scientists new to KFP, with a decompiler bridging notebooks to production repos. 38 passing tests, pilot-ready.

Start with:
- `kubekit-jupyter/CLAUDE.md` — short pointer for Claude Code sessions
- `kubekit-jupyter/HANDOFF.md` — full design brief, philosophy, state, gaps, roadmap
- `kubekit-jupyter/README.md` — user-facing docs

### Reference documents

**`platform-library-ideas.md`** — A catalog of ~40 library ideas in the same aesthetic (small, focused, deterministic core, AI on edges, composes with the platform). Grouped by category: runtime profiling, static analysis, contracts and validation, notebook productionization, experimentation, data quality, cost and environment. Use this as a backlog when deciding what to build next.

**`spark-profiler-concept.md`** — A detailed concept doc for one of the ideas in the catalog (the PySpark observability library). Shows the depth of thinking expected before starting a new library: problem, opportunity, API, architecture, sharp edges, composition story, success criteria.

**`ai-tooling-for-ml-platform.md`** (if present) — Earlier strategy doc, superseded by the more concrete artifacts above but included for context.

## The through-line

Everything in this bundle shares a pattern: **encode platform judgment as substrate, use AI for interpretation and taste calls on top, compose pieces that each earn their own place.** The working code (`kubekit-jupyter`) is one concrete instance of the pattern. The catalog is a list of other instances waiting to be built. The concept doc shows how to think about each one before starting.

## Recommended next move

Pilot `kubekit-jupyter` with one friendly, KFP-naive data scientist on one real pipeline. Document every friction point. Everything after that should be driven by what they actually hit, not speculative roadmap items.
