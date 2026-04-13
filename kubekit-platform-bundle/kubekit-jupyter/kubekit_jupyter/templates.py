"""Starter templates for data scientists new to KFP.

Each template is a fully-working example that embodies the team's standards
and can be edited in place. The goal is to let a new user go from blank
notebook to working pipeline without having to remember any KFP syntax.
"""
from __future__ import annotations

COMPONENT_TEMPLATE = '''\
%%kfp_component
from kfp import dsl
from kfp.dsl import Input, Output, Dataset, Model

@dsl.component(cpu="500m", memory="2Gi")
def {name}(
    # Pipeline parameters (scalars) come first.
    example_param: str,
    # Input artifacts from upstream components come next.
    # input_data: Input[Dataset],
    # Output artifacts this component produces come last.
    # output_model: Output[Model],
) -> str:
    """TODO: describe what {name} does.

    Rename parameters, add the real logic, remove the placeholders.
    The @dsl.component decorator turns this function into a KFP component.
    Do NOT use print() — use the platform logger.
    """
    from kubekit.logging import get_logger
    log = get_logger(__name__)
    log.info("{name}.start", example_param=example_param)

    # TODO: your logic here. A few common patterns:
    #   - Read from Snowflake:  from kubekit.snowflake import query; df = query("SELECT ...")
    #   - Read from S3:         import pandas as pd; df = pd.read_parquet(input_data.path)
    #   - Write an artifact:    output_model.path + "/model.pkl"

    log.info("{name}.done")
    return "ok"
'''


PIPELINE_TEMPLATE = '''\
%%kfp_pipeline
import kubekit_jupyter as kubekit
from kfp import dsl

@kubekit.pipeline(name="{name}", owner="{owner}")
@dsl.pipeline(name="{name}")
def {name}(
    # Pipeline parameters the scheduler will fill in. Give them defaults.
    train_date: str = "2026-04-01",
    model_version: str = "v1",
):
    """TODO: describe what this pipeline produces.

    Wire together the components you defined above. Each call creates a
    KFP task; artifacts flow by passing one task's .outputs to another's
    parameters.
    """
    # Example wiring — replace with your actual components:
    # features = load_features(train_date=train_date)
    # model    = train_model(data=features.outputs["output"], version=model_version)
    pass
'''


def render_component(name: str) -> str:
    return COMPONENT_TEMPLATE.format(name=name)


def render_pipeline(name: str, owner: str) -> str:
    return PIPELINE_TEMPLATE.format(name=name, owner=owner)


EXAMPLES: dict[str, str] = {
    "artifact": '''\
%%kfp_component
# How to pass a dataset artifact between two components.
# The upstream component writes to output.path; the downstream reads from input.path.
from kfp import dsl
from kfp.dsl import Input, Output, Dataset

@dsl.component(cpu="500m", memory="2Gi")
def make_dataset(n_rows: int, output: Output[Dataset]) -> None:
    import pandas as pd
    df = pd.DataFrame({"x": range(n_rows)})
    df.to_parquet(output.path)

@dsl.component(cpu="500m", memory="2Gi")
def use_dataset(input: Input[Dataset]) -> int:
    import pandas as pd
    df = pd.read_parquet(input.path)
    return len(df)
''',

    "snowflake": '''\
%%kfp_component
# How to read from Snowflake inside a component.
# Use kubekit.snowflake which handles auth and connection pooling for you.
from kfp import dsl
from kfp.dsl import Output, Dataset

@dsl.component(cpu="2", memory="8Gi")
def load_transactions(train_date: str, output: Output[Dataset]) -> None:
    from kubekit.logging import get_logger
    from kubekit.snowflake import query
    log = get_logger(__name__)

    log.info("load.start", date=train_date)
    df = query("""
        SELECT user_id, amount, merchant_category, txn_ts
        FROM FRAUD.TRANSACTIONS
        WHERE DATE(txn_ts) = %(date)s
    """, params={"date": train_date})
    df.to_parquet(output.path)
    log.info("load.done", rows=len(df))
''',

    "model": '''\
%%kfp_component
# How to train a model and write it as an artifact.
# The Output[Model] gives you a path to write to; the downstream component
# can load it via Input[Model].
from kfp import dsl
from kfp.dsl import Input, Output, Dataset, Model

@dsl.component(cpu="4", memory="16Gi")
def train_model(
    data: Input[Dataset],
    model: Output[Model],
    learning_rate: float = 0.01,
) -> float:
    from kubekit.logging import get_logger
    import pandas as pd
    import pickle
    log = get_logger(__name__)

    df = pd.read_parquet(data.path)
    log.info("train.start", rows=len(df), lr=learning_rate)

    # TODO: your real model here. Placeholder for the pattern:
    trained = {"weights": [0.1, 0.2, 0.3], "lr": learning_rate}
    with open(f"{model.path}/model.pkl", "wb") as f:
        pickle.dump(trained, f)

    auc = 0.85  # TODO: compute real metric
    log.info("train.done", auc=auc)
    return auc
''',

    "params": '''\
%%kfp_pipeline
# How pipeline parameters flow to components.
# The pipeline parameters become the scheduler's inputs; pass them to
# components as keyword arguments.
import kubekit_jupyter as kubekit
from kfp import dsl

@kubekit.pipeline(name="example_with_params", owner="you@example.com")
@dsl.pipeline(name="example_with_params")
def example_pipeline(
    train_date: str = "2026-04-01",
    learning_rate: float = 0.01,
    model_version: str = "v1",
):
    data = load_transactions(train_date=train_date)
    model = train_model(data=data.outputs["output"], learning_rate=learning_rate)
''',

    "logger": '''\
# The platform logger. Use it instead of print().
# Structured fields are searchable and flow into inference-logger.
from kubekit.logging import get_logger
log = get_logger(__name__)

# Good: structured events with typed fields
log.info("training.start", model="velocity_v3", rows=42000)
log.warning("feature.stale", name="user_txn_7d", age_hours=6)
log.error("snowflake.timeout", query_id="abc123", seconds=120)

# Bad: formatted strings lose their structure
# log.info(f"training started with {rows} rows")  # don't do this
''',
}


def render_example(topic: str) -> str | None:
    return EXAMPLES.get(topic)


def list_examples() -> list[str]:
    return sorted(EXAMPLES.keys())


WALKTHROUGH = """\
Welcome to kubekit-jupyter. If you're new to KFP, here's the whole flow:

  1.  %load_ext kubekit_jupyter
  2.  %kfp_new component load_features        → paste into next cell, edit, run
  3.  %kfp_new component train_model          → paste into next cell, edit, run
  4.  %kfp_new pipeline fraud_training        → paste into next cell, edit, run
  5.  %kfp_decompile ./out/fraud-training     → get a production-ready repo
  6.  Open NEXT_STEPS.md in the generated repo and follow the checklist.

At each step, use %kfp_standards <topic> to see the conventions:
  component, pipeline, resources, logging, secrets.

If anything goes wrong, the error message will tell you what to do next.
"""
