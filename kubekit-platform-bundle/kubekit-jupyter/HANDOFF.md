# HANDOFF.md — kubekit-jupyter and the broader platform story

This document is the authoritative brief for any future session (Claude Code or human) picking up this work. It captures the current state, the design philosophy, the decisions made and why, the open gaps, and a prioritized set of next moves. Read this top-to-bottom before changing code.

## The one-paragraph summary

`kubekit-jupyter` is a Jupyter magics package that makes authoring KFP v2 pipelines pleasant for data scientists — especially those new to KFP — and bridges their notebook work to production repos via a decompiler. The core story: **data scientists write pipelines in notebooks where they're productive, and when they're ready for production, one command produces a clean, standards-compliant repo ready for review.** The package enforces the team's platform standards at authoring time (not post-hoc review time), teaches the conventions through explainable validator findings, and composes with the existing platform (`kubekit`, `inference-logger`).

## Design philosophy — do not violate these

These principles have been tested against a number of design choices in this session. If a future change feels like it contradicts one of them, stop and reconsider.

1. **Deterministic core, AI on the edges.** Validators, the source extractor, the rules engine, the decompiler, and the trace store all work without any AI. Claude is reserved for *explanation* (narrating findings in plain English), *taste calls* (naming suggestions, component boundary feedback), and *fuzzy matching* (typo correction). Never put AI in a path where correctness depends on it. Users must be able to trust the tool when the AI layer is unavailable, slow, or wrong.

2. **Fail closed.** If validation finds errors, the cell does not execute and the broken component is not defined in the notebook namespace. Bad code should not be able to sneak into downstream cells. This is deliberate, not accidental.

3. **Legible output.** Every file the decompiler emits has a header explaining it was decompiled and should be reviewed. Every failure state in the tool produces a message that says what happened and what to do next. The user should never need to ping the platform team to understand why something didn't work.

4. **One-way decompilation.** The notebook is the source of truth until decompile; after that, the repo is. No automatic round-trip, no merge reconciliation, no sync hell. A user who wants to go back into notebook-land starts a new notebook session from the repo via `%kfp_import` (future work). This keeps the mental model simple.

5. **Meet users where they are.** The bet is that notebooks and SQL/Jinja can be made production-grade with enough tooling, rather than being replaced with "proper" code. Do not fight this. Every feature should respect that data scientists will continue writing notebooks, and the tooling's job is to make that safe.

6. **Two-kwarg contracts, not manifests.** We deliberately rejected a heavy `nb-contract` framework in favor of a single `@kubekit.pipeline(name=..., owner=...)` decorator. The structure data scientists must add is minimal (two kwargs, one decorator). Resist any suggestion to require more declaration up front. If the decompiler needs more information, infer it or ask at decompile time.

7. **Substrate first, AI second.** Build the deterministic core, pilot it with a real data scientist, and only then add intelligence informed by what they actually changed. Plausible-looking-but-wrong AI output destroys trust faster than ugly-but-correct deterministic output earns it.

8. **Adding a rule is a 10-line change.** The rules engine is structured so that a new rule is one decorator-registered function plus one test. If adding a rule requires more than that, something has gone wrong with the abstraction.

## Current state

### Package layout

```
kubekit-jupyter/
├── README.md                      user-facing docs
├── HANDOFF.md                     this file
├── pyproject.toml                 dependencies, pytest config, [ai] and [dev] extras
├── kubekit_jupyter/
│   ├── __init__.py                re-exports `pipeline` decorator, loads magics
│   ├── magics.py                  all IPython magics (the user-facing surface)
│   ├── validators.py              rules engine for %%kfp_component
│   ├── results.py                 Finding, Severity, ComponentResult (rich HTML repr)
│   ├── source.py                  function source extraction with decorator support
│   ├── pipeline.py                PipelineResult, PipelineRegistry, ComponentRegistry
│   ├── decorators.py              @kubekit.pipeline decorator
│   ├── traces.py                  silent component-call trace capture
│   ├── decompile.py               deterministic decompiler → production repo
│   ├── templates.py               component/pipeline templates, examples, walkthrough
│   └── standards.py               platform standards documentation strings
└── tests/
    ├── conftest.py                registry reset fixture, fake kfp, tmp_out fixture
    ├── test_validators.py         9 tests, one per rule + invariants
    ├── test_source.py             8 tests, decorator preservation is the key one
    ├── test_decompile.py          8 tests, end-to-end file generation
    └── test_templates.py          13 tests, including "scaffolded template passes validation"
```

### Magics shipped

- `%kfp_walkthrough` — 6-step onboarding tour for new users
- `%kfp_new component <name>` — scaffold a compliant component cell via `set_next_input`
- `%kfp_new pipeline <name>` — scaffold a pipeline cell via `set_next_input`
- `%kfp_example <topic>` — drop a worked example into the next cell. Topics: `artifact`, `snowflake`, `model`, `params`, `logger`
- `%%kfp_component` — validate + execute + capture source + wrap for tracing. Fails closed on errors. Findings render with expandable "why" explanations
- `%%kfp_pipeline` — evaluate a pipeline cell, register for decompilation, capture raw source for fallback
- `%kfp_decompile <out_dir>` — emit a production repo from the most recent pipeline
- `%kfp_standards [<topic>]` — print platform conventions
- `%kfp_explain <run_id>` — stub for failed-run diagnosis (v2)

### Validator rules shipped

Each rule lives in `validators.py` as a function decorated with `@rule` and produces `Finding` objects with `severity`, `rule`, `message`, `suggestion`, and `why` fields. The five current rules:

1. `no-component` / `missing-decorator` — cell must define exactly one `@component`-decorated function
2. `missing-resources` — component decorator must declare `cpu=`/`memory=` (warn)
3. `missing-annotation` — every parameter must have a type annotation (error; KFP needs them for artifact wiring)
4. `bare-print` — components must use the platform logger, not `print()` (warn)
5. `hardcoded-secret` — variables named like credentials with string-literal values are flagged (error)

Every rule ships with a `why` paragraph explaining the rationale in new-user terms. This is enforced by `test_every_rule_has_a_why_explanation` — adding a rule without a `why` breaks the suite.

### Decompiler output

Running `%kfp_decompile ./out/my-pipeline` produces:

```
out/my-pipeline/
├── README.md              generated from metadata, not hand-editable
├── NEXT_STEPS.md          7-section checklist specific to this pipeline
├── Jenkinsfile            team template with pipeline name and owner substituted
├── pyproject.toml         with [tool.kubekit] owner field
├── pipeline.py            the pipeline function, source recovered via fallback chain
├── components/
│   ├── __init__.py
│   └── <name>.py          per component; real body if captured, explanatory placeholder otherwise
└── tests/
    ├── __init__.py
    └── test_<name>.py     trace-derived regression test or pytest.skip placeholder
```

`NEXT_STEPS.md` conditionally includes a "Components that still need bodies" section when some components referenced by the pipeline weren't captured via `%%kfp_component`. This is the "partial decompile produces a partial repo, not a crash" invariant.

### What's verified

The test suite has 38 tests, all passing in ~200ms. The invariants pinned:

- Every validator rule fires correctly on a minimal failing cell and doesn't fire on a clean one
- Every rule carries a `why` explanation (self-teaching invariant)
- Source extraction preserves decorators (regression guard against the bug that silently stripped resource specs)
- `functools.wraps`-wrapped components are correctly unwrapped for source extraction
- Decompile output contains all expected files, component bodies when captured, and placeholders with `NEXT_STEPS.md` callouts when not
- Scaffolded component templates pass validation on first run (so new users see green on their first shift-enter)
- Every example in the `EXAMPLES` dict parses as valid Python (parameterized test, grows automatically)
- Pipeline source is correctly recovered via the cell-text fallback when `inspect.getsource()` fails

## Known gaps (ordered by importance)

1. **No real pilot has been run.** Everything here is informed by imagining what a new KFP user needs. The single most valuable next move is sitting with one KFP-naive data scientist on one real pipeline and watching where they get stuck. Every feature after that should be driven by what they hit, not what we predict.

2. **Trace store is process-local.** Traces captured in one kernel session vanish on restart. Keying traces by notebook path and persisting to `~/.kubekit/traces/` is maybe 50 lines of `json.dump`/`json.load` plus a path hash. Relevant only if the pilot shows data scientists actually running components and decompiling in different sessions, which they might not.

3. **Component bodies are captured from cells, not from the compiled KFP spec.** v1 relies on `%%kfp_component` having been run for every component before decompile. If a data scientist imports a component function from another module without running it through the magic, the decompiler emits a placeholder. A more ambitious version would introspect the compiled KFP pipeline spec and recover component bodies from there, which would work for any component regardless of how it was defined. This is v2 territory.

4. **No AI layer in the decompiler yet.** Naming suggestions, component boundary feedback, and meaningful test assertions are all deferred until there's real pilot output to inform the prompts. Do not build these speculatively.

5. **No `%%kfp_audit` magic.** A full-notebook audit that runs the validators against every component cell and produces a summary would be useful for the "am I ready to decompile?" moment. Straightforward extension — reuse `validate_component_source` across all registered components.

6. **No `%%plan_lint` or `%%guard_sql` magics.** These are on the broader roadmap in `platform-library-ideas.md` and would complement `%%kfp_component` for Spark and SQL cells. Each depends on a separate library (`plan-lint`, `guard-sql`) existing first. Not blocking the kubekit-jupyter pilot.

7. **The `%kfp_explain` magic is a stub.** It should pull logs, resource metrics, and recent commits from a failed run and hand them to Claude for diagnosis. Same structured-input/structured-output pattern as `explain_findings` in `validators.py`. Deferred until there's a kubekit run client to call.

8. **Tests don't cover the magics themselves.** The magics are thin wrappers over functions that are fully covered, so the business logic is protected, but IPython-specific behavior (the `set_next_input` calls, the `display(HTML(...))` output) is not asserted on. Acceptable trade for now; worth revisiting if magic-layer bugs start slipping through.

9. **No `%kfp_import` to bring a repo back into a notebook session.** Mentioned in the design philosophy as the "soft round-trip" answer but not built. Only matters if the one-way decompilation starts feeling too restrictive during the pilot.

## How to continue from here

### If you're making a small code change

1. Run `pytest -q` first and confirm the suite is green before you start
2. Make the change
3. Run `pytest -q` again
4. If you added a rule, add a test in `tests/test_validators.py` next to the existing ones
5. If you added a template or example, the parameterized tests in `tests/test_templates.py` will catch parse errors automatically, but add a content-specific test if there's a semantic invariant worth pinning

### If you're adding a new magic

1. Define the logic as a standalone function in the appropriate module (`templates.py`, `validators.py`, `decompile.py`). The magic itself should be a thin wrapper.
2. Add the magic method to `KubekitMagics` in `magics.py`. Use `@cell_magic` for `%%name` and `@line_magic` for `%name`.
3. Update the walkthrough in `templates.py` if the magic is part of the new-user flow.
4. Update the README.
5. Write a test for the underlying function, not the magic itself.

### If you're adding a new feature to the decompiler

1. Write the helper as a new `_write_*` function in `decompile.py`. Look at `_write_next_steps` for the pattern — it takes `out` and `result`, returns a `Path`, and reads from registries if needed.
2. Add the call to `decompile()` in the main sequence.
3. Add an integration test to `test_decompile.py` that asserts on file contents.
4. If the feature adds AI-powered logic, it must have a deterministic fallback that produces something useful on its own.

### If a data scientist pilot has happened and you're iterating

1. Document every friction point they hit in this HANDOFF.md under "Pilot findings" before fixing anything. The list is more valuable than any individual fix because it reveals patterns.
2. Prioritize fixes by how often they blocked progress, not how hard they are to fix. A confusing error message that hit them 5 times outranks an exotic bug that hit once.
3. Add regression tests for every fix so the friction point can't come back silently.
4. Resist the urge to add AI anywhere until you've exhausted deterministic improvements.

## File reference — what each module does and why

### `magics.py`
The only module that depends on IPython. All magics are defined here as thin wrappers over functions in other modules. Do not put business logic here; it belongs in the modules below so it can be tested without IPython installed.

### `validators.py`
The rules engine. Rules are functions decorated with `@rule` that take a source string and a parsed AST and return a list of `Finding` objects. The `validate_component_source()` function is the public entry point; it parses the source, runs all registered rules, and aggregates findings. `explain_findings()` is the optional AI layer that takes a list of findings and asks Claude to narrate them. **The AI layer does not discover problems — it explains them.**

### `results.py`
`Finding`, `Severity`, and `ComponentResult` dataclasses. Rich `_repr_html_` methods render findings as notebook-friendly cards with color-coded severity and expandable "why" details. The `ComponentResult` object is both scriptable (`.ok`, `.errors`, `.warnings`, `.explain()`) and visually rich — the "transparent magic" principle.

### `source.py`
Function source extraction. Two entry points: `extract_function_source(fn, fallback_cell=...)` tries `inspect.getsource()` first and falls back to text-based extraction from the raw cell; `extract_function_source_from_text(name, text)` is a pure function useful for testing. **The critical invariant is that decorators must be preserved** — this file has the subtlest regression surface in the package and the decorator preservation test is the most important test in the suite.

### `pipeline.py`
`PipelineResult` dataclass (captures pipeline function, metadata, component names, raw cell source). `PipelineRegistry` and `ComponentRegistry` — process-global singletons that store the most recent pipeline and all captured component source respectively. The autouse fixture in `conftest.py` clears these between tests; without it, state leaks across tests.

### `decorators.py`
Defines `@kubekit.pipeline(name=..., owner=...)`. The decorator attaches `PipelineMetadata(name, owner)` to the function as `__kubekit_metadata__`. That's the entire "contract" — two kwargs, no framework.

### `traces.py`
Silent trace capture. `%%kfp_component` wraps each executed component with a `functools.wraps` wrapper that records a `Trace(component_name, args_repr, return_repr)` on every call. The `TraceStore` is process-global. `short_repr()` produces a stable, bounded representation of any value for inclusion in traces.

### `decompile.py`
The deterministic decompiler. Top-level function is `decompile(result, out_dir)`. Each generated file has a corresponding `_write_*` helper. No AI anywhere in this module yet — that's deliberate, per the "substrate first" principle.

### `templates.py`
Starter templates (`COMPONENT_TEMPLATE`, `PIPELINE_TEMPLATE`), worked examples (`EXAMPLES` dict), and the onboarding walkthrough (`WALKTHROUGH` string). `render_component()`, `render_pipeline()`, and `render_example()` are the public functions. Templates deliberately embody the team standards so `test_component_template_passes_validation` is a forcing function keeping templates and rules in sync.

### `standards.py`
Platform convention strings keyed by topic. Pure data module — no logic. When the `platform-standards` library (see `platform-library-ideas.md`) is built, this module's contents should migrate there and `standards.py` becomes a thin shim.

## The broader platform story

This package is one piece of a larger strategy. See the two companion documents in this bundle:

- **`platform-library-ideas.md`** — a catalog of ~40 library ideas in the same aesthetic (small, focused, deterministic core, AI on edges, composes with the platform). Ordered by category: runtime profiling, static analysis, contracts and validation, notebook productionization, experimentation, data quality, cost and environment.

- **`spark-profiler-concept.md`** — a detailed concept doc for one of the libraries, capturing the pattern to follow when writing concept docs for the others.

The libraries in that catalog and `kubekit-jupyter` are designed to compose. For example: `%%plan_lint` (a future magic) would call into a `plan-lint` library (a future package) using the same pattern `%%kfp_component` uses to call into `validators.py`. Every library is independently useful and the whole set forms a coherent platform when assembled.

## Invariants to preserve

A short list of behaviors that must not silently regress:

1. A scaffolded component template passes validation on first run
2. Every validator rule has a `why` paragraph
3. Source extraction preserves decorators
4. `functools.wraps`-wrapped components are unwrapped for source extraction
5. Partial decompile produces a partial repo with self-describing placeholders, not a crash
6. Generated files carry "Generated by `kubekit decompile`, review before merging" headers
7. `NEXT_STEPS.md` conditionally includes or omits the "missing bodies" section correctly
8. `%%kfp_component` fails closed — broken components don't get defined in the namespace
9. Adding a rule means adding one function in `validators.py` and one test in `tests/test_validators.py`

## Session history — what's been built, in order

1. **Initial scaffold**: package structure, `%%kfp_component` with 5 rules, `%kfp_standards`, `%kfp_explain` stub, rich HTML findings
2. **Pipeline and decompile**: `@kubekit.pipeline` decorator, `%%kfp_pipeline`, `PipelineRegistry`, trace capture on component execution, deterministic decompiler emitting 11 files
3. **Component body extraction**: `source.py` with `extract_function_source`, `ComponentRegistry`, decompiler consumes real component source. Caught and fixed a bug where decorators were silently stripped.
4. **New-user experience**: `templates.py` with component/pipeline templates and 5 worked examples, `%kfp_new`, `%kfp_example`, `%kfp_walkthrough`, `NEXT_STEPS.md` checklist
5. **Layered help and source recovery**: validators gained `why` paragraphs with expandable HTML rendering, pipeline source captured from cell and used as decompile fallback
6. **Test suite**: 38 tests across 4 files pinning the invariants above

Each step was taken after explicit discussion about whether it was the right next move. Do not skip that discussion for future steps — the session history shows that several candidate features were rejected or dramatically simplified after thinking about fit (the `nb-contract` framework idea was the most notable one).
