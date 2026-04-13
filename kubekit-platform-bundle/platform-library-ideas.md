# Platform Library Ideas

A working catalog of library ideas in the spirit of `kubekit`, `inference-logger`, and the Spark listener: small, focused Python packages with a deterministic core and an AI-powered interpretation layer, that compose with the existing platform and meet data scientists where they work.

## Design pattern

Every library below follows the same shape:

- **Latent instrumentation.** Captures structured data as a side effect of normal code. Data scientists don't change how they work; the library runs alongside them.
- **Deterministic core.** Rules engines, validators, and analyzers find problems without AI. The library is useful and trustworthy even if the AI layer is unavailable.
- **AI on the edges.** Claude is used for explanation, ranking, fix generation, and fuzzy matching — never for core correctness.
- **Composes with the platform.** Events flow into `inference-logger`; validators stack with `config-guard` and `kubekit` hooks.

A shared event format and a shared AI-explanation layer would make each new library ~200-400 lines instead of ~800-1200.

## Runtime profiling and observability

- **`spark-profiler`** — PySpark listener that captures structured metrics, runs a rules engine over them, and uses Claude to explain findings and suggest fixes. Concept doc exists separately.
- **`sql-profile`** — Snowflake equivalent. Parses query history API, surfaces bytes scanned, partitions pruned, warehouse queuing, spillage. AI explains why queries are slow or expensive and suggests rewrites.
- **`queue-sense`** — Wraps Kafka and internal streaming consumers with typed lag and throughput metrics. AI analyzes lag patterns and suggests rebalancing, scaling, or upstream producer issues. Relevant to velocity-features work.
- **`async-trace`** — Captures structured traces across async boundaries in Python ML services. AI reads a trace and explains where time went. Useful for real-time inference services.
- **`retry-radar`** — Wraps flaky external calls with structured retry metadata. AI detects when "flaky" is actually systematic.

## Static analysis and linting

- **`plan-lint`** — Static linter for PySpark query plans. Analyzes the logical plan at construction time and flags exploded cross joins, missing broadcast hints, predicate placement issues, and pushdown opportunities. Ships as a Jupyter cell magic and a CI check. Claude rewrites offending DataFrame code with the fix.
- **`guard-sql`** — SQL wrapper that validates queries before submission against anti-patterns: `SELECT *` on wide tables, missing `LIMIT`, implicit cross joins, missing partition pruning, queries that will fan out beyond cost thresholds. Primary delivery is a Jupyter magic and a Snowflake connection wrapper.
- **`jinja-guard`** — Validates Jinja templates at both the template layer (undefined variables, deprecated macros, unescaped contexts) and the rendered output layer (valid SQL via `guard-sql`, valid config via `config-guard`). The composition layer that applies other validators to templated code.
- **`nb-lint`** — Notebook-specific linter catching production-hostile patterns: hardcoded paths, credentials in cells, out-of-order execution dependencies, `.collect()` on large frames, `pd.read_*` inside loops. Jupyter extension and CLI.
- **`kfp-doctor`** — Static introspection of KFP v2 pipelines before submission. Flags missing resource specs, missing exit handlers, circular artifact dependencies, unmarshallable return types. Ships as a kubekit pre-submission hook so bad pipelines cannot be submitted.
- **`dep-weight`** — Measures the actual cost of each import in pipeline code. Reports unused and expensive imports and suggests lazy-loading candidates.

## Contracts and validation

- **`config-guard`** — Pydantic-based config library with platform-aware validators (Snowflake catalog, feature store, K8s resources, Spark memory format, S3 paths). AI fuzzy-match layer suggests corrections for near-miss values like typoed feature names. Concept previously discussed.
- **`pipeline-contract`** — Decorator-based data contracts between KFP components. Validates schemas at runtime, logs drift. Companion `contract suggest` mode reads an existing component and proposes the contract from observed behavior.
- **`contract-check`** — Data contracts in the Great Expectations spirit but scoped narrower and opinionated for the stack. Decorators declare row count ranges, null rates, value distributions. AI explains failures and matches them against known upstream issues.
- **`safe-cast`** — Typed, logged casts between DataFrame schemas. Deterministic core enforces rules; AI explains casting failures and suggests the right target type.
- **`nb-contract`** — Declarative contract at the top of a notebook: inputs, outputs, invariants, side effects. Library validates every run against the contract. Becomes the spec the platform uses for productionization.

## Notebook and SQL productionization

- **`nb-promote`** — Takes a notebook plus an `nb-contract` and produces a draft KFP component. Deterministic core handles cell partitioning, parameter extraction, scaffold generation; AI fills in judgment calls. The missing link between exploration and production.
- **`nb-test`** — Tests written about a notebook from outside the notebook. Runs in subprocess with given parameters and asserts on outputs. Makes notebooks CI-testable without restructuring.
- **`nb-params`** — Typed parameterization (papermill-style but stricter). Generates a schema the platform uses for scheduled runs and validates inputs before execution.
- **`nb-freeze`** — Captures a notebook's full execution environment, data snapshots, and cell outputs into a frozen, reproducible artifact. AI diffs two frozen runs and explains behavioral differences.
- **`notebook-ci`** — CI framework for notebooks. Runs every notebook on every PR, diffs outputs against last-merged version, generates PR comments. One config file to set up.
- **`jinja-diff`** — Shows semantic (SQL AST) diff between two versions of a Jinja template given the same parameters. Catches "I thought my refactor was a no-op" bugs.
- **`sql-snapshot`** — Snapshot testing for SQL queries. Captures row count, schema, canonical hash. AI explains what changed when snapshots break.
- **`dbt-lite`** — SQL files with Jinja templating, a dependency graph via `ref()`-style calls, and a runner that executes in dependency order. Keeps data scientists in SQL but gives them structure. AI detects circular refs, deprecated sources, and structural anti-patterns.

## Experimentation and regression

- **`golden-set`** — Declarative regression tests on model outputs using a versioned frozen example set. Flags any prediction change beyond tolerance. AI explains why predictions changed by comparing feature values, model versions, and training data.
- **`ablate`** — Structured ablation studies via decorator. Runs the function per ablation config, captures deltas, AI generates a written summary of which features mattered and what interactions were surprising.
- **`trace-replay`** — Records inference requests to a trace store and replays them against new model versions offline. AI summarizes behavioral changes between model versions.
- **`sanity-set`** — Quick pre-deployment sanity checks as decorators. Faster and narrower than regression tests; catches obvious breakage in seconds.
- **`exp-journal`** — Thin wrapper over MLflow/W&B that adds structured hypothesis/outcome/conclusion annotations. AI generates periodic "what we learned" digests across experiments.
- **`param-sweep`** — Wrapper over Optuna/Hyperopt with structured logging and observable early stopping. AI suggests pruning or expanding branches mid-sweep.

## Data quality and lineage

- **`feature-probe`** — Wraps feature computation and captures distributional statistics on every run, keyed by feature name and date. AI detects drift and correlates it with upstream events.
- **`feature-freshness`** — Wraps feature store reads and captures feature age at read time vs. SLA. AI correlates model issues with freshness violations upstream.
- **`feature-lineage`** — Decorator-based feature lineage graph built as a side effect of normal code. No central registry.
- **`schema-witness`** — Captures DataFrame schemas at key points in a pipeline. Builds schema evolution history. AI generates migration suggestions when downstream breaks.
- **`schema-evolve`** — Declarative schema migrations for feature tables. Checks dependent pipelines and models for compatibility before allowing changes.
- **`lineage-trace`** — Table-level lineage built passively from PySpark read/write instrumentation. AI answers natural-language lineage questions.
- **`drift-sentinel`** — Wraps inference-logger output with configurable drift checks (PSI, KS, custom). AI explains why a feature drifted.

## Cost, environment, and reproducibility

- **`cost-tag`** — Decorator-based cost attribution. Captures Snowflake and Spark costs during tagged blocks and rolls them up by project, model, stage. AI answers "where did our budget go."
- **`env-snapshot`** — Captures the full execution environment of a pipeline run (package versions, Python, Spark, cluster config, env vars, git SHA) as a structured artifact. AI diffs two snapshots and explains discrepancies.
- **`run-rewind`** — Records deterministic inputs to each KFP component and lets you reconstruct or reproduce a historical run locally. AI diagnoses nondeterminism when the same inputs produce different outputs.
- **`kfp-replay`** — Library version of run-rewind focused on component-level replay for debugging.
- **`artifact-diff`** — Semantic diffing of KFP artifacts between runs. AI explains why two runs diverged by correlating with code, data, and config changes.
- **`kfp-cache-advisor`** — Analyzes KFP run history to identify good caching candidates. AI explains each recommendation and generates kubekit annotations.

## Priority notes

Two pairings stand out as highest leverage:

1. **`nb-contract` + `nb-promote`** — The bridge from exploration to production. Worthless individually; transformative together. Directly addresses the "data scientists love notebooks, notebooks aren't production-ready" tension.
2. **`spark-profiler` + `sql-profile`** — Cover the two places compute actually runs. Deterministic rules catch known issues; AI layer teaches Spark/Snowflake intuition faster than documentation ever could.

Also high-leverage: **`dbt-lite`** (structure without taking away SQL), **`kfp-doctor`** as a kubekit hook (moves failures from minute 20 to second 0), and **`golden-set`** (silent regressions destroy trust in the platform).
