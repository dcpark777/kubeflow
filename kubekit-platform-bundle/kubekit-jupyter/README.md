# kubekit-jupyter

Jupyter magics for authoring, validating, submitting, and decompiling KFP v2 pipelines without leaving the notebook. The story: data scientists write pipelines in notebooks where they are productive, and when they are ready for production, one command produces a clean repo.

## Install

    pip install kubekit-jupyter          # core
    pip install kubekit-jupyter[ai]      # adds Claude-powered explanations

Then in a notebook:

    %load_ext kubekit_jupyter

## New to KFP? Start here

If you've never written a KFP pipeline, run this and follow along:

    %kfp_walkthrough

Then use the `%kfp_new` scaffolder to generate working cells you can edit:

    %kfp_new component load_features    # drops a component template into the next cell
    %kfp_new component train_model
    %kfp_new pipeline fraud_training

Each scaffolded cell is already compliant with the team's standards — it will
pass validation on first run, and you only need to fill in the actual logic.

When your pipeline runs cleanly, one command produces a production repo:

    %kfp_decompile ./out/fraud-training

Open `NEXT_STEPS.md` in the generated repo and follow the checklist.

## The workflow

1. Write and validate components with `%%kfp_component`. The magic runs a standards audit at shift-enter and executes the cell only if there are no errors. It also wraps the component so that any calls made in the notebook record traces for later test scaffolding.

2. Define the pipeline with `%%kfp_pipeline`. The cell must contain a function decorated with `@kubekit.pipeline(name=..., owner=...)`. This is the only structural metadata the decompiler needs — everything else is implicit in the compiled pipeline.

3. When the pipeline runs cleanly and you are ready to productionize, run `%kfp_decompile <out_dir>`. You get back a repo with `pipeline.py`, `components/`, `tests/`, a `Jenkinsfile`, a `pyproject.toml`, and a `README.md`. Every file carries a header noting that it was decompiled and should be reviewed before merging.

## Magics

- `%kfp_walkthrough` — full tour for users new to KFP.
- `%kfp_new component <name>` / `%kfp_new pipeline <name>` — scaffold a ready-to-edit cell.
- `%kfp_example <topic>` — drop a worked example into the next cell. Topics: `artifact`, `snowflake`, `model`, `params`, `logger`.
- `%%kfp_component` — validate, execute, and trace a component cell. Fails closed on errors. Findings include expandable "why" explanations for users learning the conventions.
- `%%kfp_pipeline` — evaluate a pipeline cell, register it for decompilation.
- `%kfp_decompile <out_dir>` — decompile the most recent pipeline to a production repo.
- `%kfp_standards <topic>` — print platform standards (`overview`, `component`, `pipeline`, `resources`, `logging`, `secrets`).
- `%kfp_explain <run_id>` — stub for failed-run diagnosis via Claude.

## Example

```python
%load_ext kubekit_jupyter
import kubekit_jupyter as kubekit
from kfp import dsl
```

```python
%%kfp_component
@dsl.component(cpu="500m", memory="2Gi")
def load_features(train_date: str) -> dict:
    from kubekit.logging import get_logger
    log = get_logger(__name__)
    log.info("load.start", date=train_date)
    return {"rows": 1000}
```

```python
%%kfp_component
@dsl.component(cpu="4", memory="16Gi")
def train_model(data: dict, version: str) -> dict:
    return {"auc": 0.85}
```

```python
%%kfp_pipeline
@kubekit.pipeline(name="fraud_velocity_training", owner="dan@capitalone.com")
@dsl.pipeline
def training_pipeline(train_date: str, model_version: str = "v4"):
    data = load_features(train_date)
    return train_model(data, model_version)
```

```python
%kfp_decompile ./out/fraud-velocity
```

## Design notes

- **Deterministic core, AI on the edges.** Validators and the decompiler work without AI. Claude is reserved for explanation and taste calls, never for correctness.
- **Fail closed.** Broken components do not get defined in the notebook namespace.
- **One-way decompilation.** The notebook is the source of truth until you decompile; after that, the repo is. No automatic round-trip; no merge reconciliation.
- **Legible output.** Every generated file has a header explaining it was decompiled and should be reviewed.
- **Respect existing structure.** The decompiler translates the pipeline faithfully — it does not refactor. If the notebook compiled a bad structure, the repo reflects it.

## Roadmap

- Actual component-body extraction from the compiled KFP spec (v1 emits placeholders)
- Persistent trace store keyed by notebook path
- AI-layer additions: naming suggestions, meaningful test assertions, component-boundary feedback
- `%%kfp_audit` full-notebook audit
- `%%plan_lint` and `%%guard_sql` magics for Spark and SQL cells
