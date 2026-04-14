"""
spark_obs - Zero-touch Spark observability via driver logs.

Adds structured JSON logging on top of Spark's built-in driver
logs. Spark already logs task/stage/job progress — this module
adds what it doesn't: execution plans, caller-tagged timing,
task metrics for skew detection, and structured summaries you
can grep/query.

Usage:
    from spark_obs import SparkObserver

    spark = SparkSession.builder.getOrCreate()
    SparkObserver(spark)

    # That's it. All DataFrame and Writer actions are
    # automatically logged with plans, timing, and caller
    # inferred from your call stack.

Risks:
    - Monkey-patches DataFrame and DataFrameWriter action methods.
      If EMP or another library patches the same methods, one
      overwrites the other. The _obs guard prevents self-collision
      but not external collision. Test on EMP before relying on it.
    - queryExecution().simpleString() and executedPlan().metrics()
      cross the Py4J bridge. On pathological plans (deeply nested,
      many joins) the plan string serialization and metrics tree
      walk add latency before/after each action — typically <100ms
      combined, but could be higher.
    - The action list is manually maintained. If someone uses
      foreach(), toLocalIterator(), or a method not in the list,
      it won't be logged. Spark's own driver logs still capture
      those — you just won't get the structured summary.
    - Task metrics are fetched from Spark's REST API on
      localhost:4040. If EMP blocks this port or disables the
      API, metrics gracefully degrade to basic stage info from
      the statusTracker. The REST call adds a small amount of
      latency after each action (~10-50ms per stage).
    - SQL metrics walk the executed plan tree via Py4J. If EMP's
      security manager blocks access to internal Spark classes,
      sql_metrics will be absent — everything else still works.
"""

import logging
import time
import json
import traceback
import urllib.request
import urllib.error

logger = logging.getLogger("spark_obs")

LOG_SOURCE = "spark_obs"

SKIP_MODULES = frozenset([
    "pyspark", "py4j", "spark_obs", "threading", "contextlib",
])

SESSION_CONFIGS = [
    "spark.app.name",
    "spark.sql.shuffle.partitions",
    "spark.sql.adaptive.enabled",
    "spark.sql.adaptive.coalescePartitions.enabled",
    "spark.sql.autoBroadcastJoinThreshold",
    "spark.executor.memory",
    "spark.executor.cores",
    "spark.executor.instances",
    "spark.dynamicAllocation.enabled",
    "spark.dynamicAllocation.maxExecutors",
    "spark.kubernetes.executor.request.cores",
    "spark.kubernetes.executor.limit.cores",
]

DF_ACTIONS = [
    "collect", "count", "first", "take",
    "show", "toPandas", "head", "tail",
]

WRITER_ACTIONS = [
    "save", "insertInto", "saveAsTable",
    "parquet", "orc", "json", "csv",
]


class SparkObserver:
    def __init__(self, spark):
        if getattr(spark, "_spark_obs_initialized", False):
            logger.warning(json.dumps({
                "source": LOG_SOURCE,
                "event": "already_initialized",
                "description": (
                    "SparkObserver.init() called more than"
                    " once on this session, skipping"
                ),
            }))
            return

        self.spark = spark
        self.sc = spark.sparkContext
        self.tracker = self.sc.statusTracker()
        self.app_id = self.sc.applicationId
        self._rest_available = None

        self._log_session_info()
        self._patch_actions()

        spark._spark_obs_initialized = True

        logger.info(json.dumps({
            "source": LOG_SOURCE,
            "event": "observer_ready",
            "description": (
                "spark_obs patches applied to DataFrame"
                " and DataFrameWriter action methods"
            ),
        }))

    # --------------------------------------------------
    # Session info
    # --------------------------------------------------

    def _log_session_info(self):
        logger.info(json.dumps({
            "source": LOG_SOURCE,
            "event": "session_start",
            "description": (
                "Spark session configuration at job startup"
            ),
            "app_id": self.app_id,
            "config": {
                k: self.spark.conf.get(k, "unset")
                for k in SESSION_CONFIGS
            },
        }))

    # --------------------------------------------------
    # Monkey-patching
    # --------------------------------------------------

    def _patch_actions(self):
        import pyspark.sql.dataframe as df_mod
        import pyspark.sql.readwriter as rw_mod

        for name in DF_ACTIONS:
            self._patch(df_mod.DataFrame, name)
        for name in WRITER_ACTIONS:
            self._patch(rw_mod.DataFrameWriter, name)

    def _patch(self, cls, method_name):
        original = getattr(cls, method_name, None)
        if not original or getattr(original, "_obs", False):
            return

        observer = self
        qualified_action = f"{cls.__name__}.{method_name}"

        def patched(df_self, *args, **kwargs):
            # Pre-execution observation — if this fails,
            # fall through and run the action unobserved.
            caller = None
            plan = None
            jobs_before = None
            start = time.time()

            try:
                caller = _infer_caller()
                jobs_before = set(
                    observer.tracker.getJobIdsForGroup(None)
                )
                plan = _get_plan(df_self)
            except Exception:
                pass

            # The actual Spark action — never wrapped in
            # observation error handling. If THIS fails,
            # it's a real Spark error and must propagate.
            try:
                result = original(df_self, *args, **kwargs)
            except Exception as e:
                try:
                    _log_failure(
                        caller, qualified_action,
                        start, plan, e,
                    )
                except Exception:
                    pass
                raise

            # Post-execution observation — if this fails,
            # the action already succeeded, just skip logging.
            try:
                sql_metrics = _get_sql_metrics(df_self)
                _log_success(
                    observer, caller, qualified_action,
                    start, plan, jobs_before, sql_metrics,
                )
            except Exception:
                pass

            return result

        patched._obs = True
        setattr(cls, method_name, patched)

    # --------------------------------------------------
    # REST API for task metrics
    # --------------------------------------------------

    def _check_rest_api(self):
        """Check once whether the Spark REST API is reachable."""
        if self._rest_available is not None:
            return self._rest_available
        try:
            url = (
                f"http://localhost:4040"
                f"/api/v1/applications/{self.app_id}"
            )
            req = urllib.request.Request(url, method="GET")
            urllib.request.urlopen(req, timeout=2)
            self._rest_available = True
        except Exception:
            self._rest_available = False
            logger.info(json.dumps({
                "source": LOG_SOURCE,
                "event": "rest_api_unavailable",
                "description": (
                    "Spark REST API not reachable on"
                    " localhost:4040, task-level metrics"
                    " disabled"
                ),
            }))
        return self._rest_available

    def get_task_metrics(self, stage_id, attempt=0):
        """Fetch per-task metrics from the Spark REST API.
        Returns a skew summary or None if unavailable."""
        if not self._check_rest_api():
            return None
        try:
            url = (
                f"http://localhost:4040"
                f"/api/v1/applications/{self.app_id}"
                f"/stages/{stage_id}/{attempt}"
            )
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read())

            tasks = data.get("tasks", {})
            if not tasks:
                return None

            durations = []
            shuffle_reads = []
            shuffle_writes = []
            records_read = []

            for task in tasks.values():
                metrics = task.get("taskMetrics", {})
                durations.append(
                    metrics.get("executorRunTime", 0)
                )

                sr = metrics.get("shuffleReadMetrics", {})
                shuffle_reads.append(
                    sr.get("localBytesRead", 0)
                    + sr.get("remoteBytesRead", 0)
                )

                sw = metrics.get("shuffleWriteMetrics", {})
                shuffle_writes.append(
                    sw.get("bytesWritten", 0)
                )

                inp = metrics.get("inputMetrics", {})
                records_read.append(
                    inp.get("recordsRead", 0)
                )

            return _summarize_distribution(
                durations, shuffle_reads,
                shuffle_writes, records_read,
            )
        except Exception:
            return None


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def _infer_caller():
    for frame in reversed(traceback.extract_stack()):
        if any(skip in frame.filename for skip in SKIP_MODULES):
            continue
        filename = frame.filename.rsplit("/", 1)[-1]
        return f"{filename}:{frame.name}:{frame.lineno}"
    return "unknown"


def _get_jdf(df_self):
    """Extract the underlying Java DataFrame from either
    a DataFrame or DataFrameWriter."""
    jdf = getattr(df_self, "_jdf", None)
    if jdf is None:
        inner = getattr(df_self, "_df", None)
        if inner:
            jdf = getattr(inner, "_jdf", None)
    return jdf


def _get_plan(df_self):
    try:
        jdf = _get_jdf(df_self)
        if jdf:
            return jdf.queryExecution().simpleString()[:2000]
    except Exception:
        pass
    return None


def _get_sql_metrics(df_self):
    """Extract per-operator metrics from the executed plan.
    This is the SQL tab equivalent — row counts, data sizes,
    etc. per node in the physical plan.

    Must be called AFTER the action completes, since the
    metrics are only populated post-execution."""
    try:
        jdf = _get_jdf(df_self)
        if not jdf:
            return None

        executed_plan = (
            jdf.queryExecution().executedPlan()
        )
        return _walk_plan_metrics(executed_plan)
    except Exception:
        return None


def _walk_plan_metrics(node, depth=0, max_depth=20):
    """Recursively walk the SparkPlan tree and extract
    metrics from each node."""
    if depth > max_depth:
        return []

    operators = []

    try:
        name = node.nodeName()
        metrics = {}

        # node.metrics() returns a Map[String, SQLMetric]
        metrics_map = node.metrics()
        keys = list(metrics_map.keys())

        for key in keys:
            try:
                metric = metrics_map.apply(key)
                value = metric.value()
                if value > 0:
                    metrics[key] = value
            except Exception:
                continue

        if metrics:
            operators.append({
                "operator": str(name),
                "metrics": metrics,
            })

        # Recurse into children
        children = node.children()
        for i in range(children.length()):
            child = children.apply(i)
            operators.extend(
                _walk_plan_metrics(child, depth + 1)
            )
    except Exception:
        pass

    return operators


def _summarize_distribution(
    durations, shuffle_reads, shuffle_writes, records_read,
):
    """Compute p50/p95/max for task metrics to surface skew."""
    def _percentiles(values):
        if not values:
            return None
        s = sorted(values)
        n = len(s)
        return {
            "min": s[0],
            "p50": s[n // 2],
            "p95": s[int(n * 0.95)],
            "max": s[-1],
        }

    result = {}

    dur = _percentiles(durations)
    if dur and dur["max"] > 0:
        result["duration_ms"] = dur

    sr = _percentiles(shuffle_reads)
    if sr and sr["max"] > 0:
        result["shuffle_read_bytes"] = sr

    sw = _percentiles(shuffle_writes)
    if sw and sw["max"] > 0:
        result["shuffle_write_bytes"] = sw

    rr = _percentiles(records_read)
    if rr and rr["max"] > 0:
        result["records_read"] = rr

    return result if result else None


def _log_failure(caller, action, start, plan, error):
    logger.error(json.dumps({
        "source": LOG_SOURCE,
        "event": "action_failed",
        "description": (
            "Spark action failed with exception"
        ),
        "caller": caller,
        "action": action,
        "elapsed_seconds": round(time.time() - start, 2),
        "error": str(error),
        "execution_plan": plan,
    }))


def _log_success(
    observer, caller, action, start, plan,
    jobs_before, sql_metrics,
):
    elapsed = time.time() - start

    stages = []
    new_jobs = []

    if jobs_before is not None:
        new_jobs = sorted(
            set(observer.tracker.getJobIdsForGroup(None))
            - jobs_before
        )

        for jid in new_jobs:
            job_info = observer.tracker.getJobInfo(jid)
            if job_info:
                for sid in job_info.stageIds:
                    info = observer.tracker.getStageInfo(sid)
                    if info:
                        stage = {
                            "stage_id": sid,
                            "tasks_total": info.numTasks,
                            "tasks_completed": info.numCompletedTasks,
                            "tasks_failed": info.numFailedTasks,
                        }

                        metrics = observer.get_task_metrics(sid)
                        if metrics:
                            stage["task_metrics"] = metrics

                        stages.append(stage)

    entry = {
        "source": LOG_SOURCE,
        "event": "action_complete",
        "description": (
            "Completed Spark action triggered by user code"
        ),
        "caller": caller,
        "action": action,
        "job_ids": new_jobs,
        "elapsed_seconds": round(elapsed, 2),
        "stages": stages,
        "execution_plan": plan,
    }

    if sql_metrics:
        entry["sql_metrics"] = sql_metrics

    logger.info(json.dumps(entry))


# --------------------------------------------------
# Log analysis
# --------------------------------------------------

def analyze(log_lines):
    """Analyze spark_obs log lines and return findings.

    Args:
        log_lines: iterable of strings (raw log lines).
            Can be a file object, list of strings, or
            anything iterable. Non-spark_obs lines are
            ignored.

    Returns:
        dict with keys:
            config: session config if found
            actions: list of action summaries
            findings: list of human-readable observations
                about performance, skew, and config issues

    Usage:
        with open("driver.log") as f:
            report = spark_obs.analyze(f)

        for finding in report["findings"]:
            print(finding)
    """
    events = _parse_events(log_lines)

    config = None
    actions = []
    findings = []

    for evt in events:
        event_type = evt.get("event")

        if event_type == "session_start":
            config = evt.get("config", {})
            findings.extend(_check_config(config))

        elif event_type == "action_complete":
            summary = _summarize_action(evt)
            actions.append(summary)
            findings.extend(summary.get("findings", []))

        elif event_type == "action_failed":
            actions.append({
                "caller": evt.get("caller"),
                "action": evt.get("action"),
                "elapsed_seconds": evt.get("elapsed_seconds"),
                "status": "failed",
                "error": evt.get("error"),
                "findings": [
                    f"FAILURE: {evt.get('caller')} ->"
                    f" {evt.get('action')} failed after"
                    f" {evt.get('elapsed_seconds')}s:"
                    f" {evt.get('error')}"
                ],
            })

    # Cross-action findings
    if actions:
        findings.extend(_cross_action_findings(actions))

    return {
        "config": config,
        "actions": actions,
        "findings": findings,
    }


def _parse_events(log_lines):
    """Extract spark_obs JSON events from raw log lines."""
    events = []
    for line in log_lines:
        # Find JSON in the line
        start = line.find("{")
        if start == -1:
            continue
        try:
            data = json.loads(line[start:])
            if data.get("source") == LOG_SOURCE:
                events.append(data)
        except (json.JSONDecodeError, ValueError):
            continue
    return events


def _check_config(config):
    """Flag common config issues."""
    findings = []

    partitions = config.get(
        "spark.sql.shuffle.partitions", "unset"
    )
    if partitions == "200":
        findings.append(
            "CONFIG: spark.sql.shuffle.partitions is at"
            " default (200). Consider tuning based on"
            " data size — too high wastes overhead on"
            " small data, too low causes large partitions."
        )

    aqe = config.get(
        "spark.sql.adaptive.enabled", "unset"
    )
    if aqe != "true":
        findings.append(
            "CONFIG: Adaptive Query Execution (AQE) is"
            f" '{aqe}'. Enabling it lets Spark auto-tune"
            " shuffle partitions and join strategies at"
            " runtime."
        )

    broadcast = config.get(
        "spark.sql.autoBroadcastJoinThreshold", "unset"
    )
    if broadcast == "-1":
        findings.append(
            "CONFIG: Broadcast joins are disabled"
            " (threshold=-1). Small dimension tables"
            " will use SortMergeJoin, which is slower."
        )

    dynamic = config.get(
        "spark.dynamicAllocation.enabled", "unset"
    )
    instances = config.get(
        "spark.executor.instances", "unset"
    )
    if dynamic != "true" and instances == "unset":
        findings.append(
            "CONFIG: Dynamic allocation is off and"
            " executor.instances is unset. The job may"
            " not get enough executors."
        )

    return findings


def _summarize_action(evt):
    """Analyze a single action_complete event."""
    findings = []
    caller = evt.get("caller")
    action = evt.get("action")
    elapsed = evt.get("elapsed_seconds", 0)
    stages = evt.get("stages", [])

    # Check for task failures
    total_failed = sum(
        s.get("tasks_failed", 0) for s in stages
    )
    if total_failed > 0:
        findings.append(
            f"TASK FAILURES: {caller} -> {action} had"
            f" {total_failed} failed tasks across"
            f" {len(stages)} stages. Check executor logs"
            " for OOM or fetch failures."
        )

    # Check for skew via task metrics
    for stage in stages:
        tm = stage.get("task_metrics")
        if not tm:
            continue

        dur = tm.get("duration_ms")
        if dur:
            ratio = (
                dur["max"] / dur["p50"]
                if dur["p50"] > 0 else 0
            )
            if ratio > 10:
                findings.append(
                    f"SKEW: {caller} -> stage"
                    f" {stage['stage_id']} has task"
                    f" duration skew — max"
                    f" {dur['max']}ms is {ratio:.0f}x"
                    f" the median {dur['p50']}ms."
                    " Consider salting the join key or"
                    " repartitioning."
                )

        sr = tm.get("shuffle_read_bytes")
        if sr:
            ratio = (
                sr["max"] / sr["p50"]
                if sr["p50"] > 0 else 0
            )
            if ratio > 10:
                findings.append(
                    f"SKEW: {caller} -> stage"
                    f" {stage['stage_id']} has shuffle"
                    f" read skew — max partition is"
                    f" {ratio:.0f}x the median."
                )

    # Check execution plan for common issues
    plan = evt.get("execution_plan", "") or ""

    if "SortMergeJoin" in plan:
        # Check if one side is small via sql_metrics
        sql_m = evt.get("sql_metrics", [])
        scan_rows = [
            op["metrics"].get("number of output rows", 0)
            for op in sql_m
            if "Scan" in op.get("operator", "")
        ]
        if scan_rows and min(scan_rows) < 1_000_000:
            findings.append(
                f"JOIN STRATEGY: {caller} uses"
                " SortMergeJoin but one input has"
                f" {min(scan_rows):,} rows — consider"
                " increasing"
                " spark.sql.autoBroadcastJoinThreshold"
                " or adding a broadcast hint."
            )

    if "CartesianProduct" in plan:
        findings.append(
            f"CARTESIAN: {caller} has a CartesianProduct"
            " in the plan — this is almost always"
            " unintentional and will explode with data"
            " size."
        )

    # Check for row explosion via sql_metrics
    sql_m = evt.get("sql_metrics", [])
    if len(sql_m) >= 2:
        row_counts = [
            (op["operator"], op["metrics"].get(
                "number of output rows", 0
            ))
            for op in sql_m
            if "number of output rows" in op.get(
                "metrics", {}
            )
        ]
        for i in range(len(row_counts) - 1):
            curr_op, curr_rows = row_counts[i]
            next_op, next_rows = row_counts[i + 1]
            if (
                next_rows > 0
                and curr_rows > next_rows * 10
                and "Join" in curr_op
            ):
                findings.append(
                    f"ROW EXPLOSION: {caller} ->"
                    f" {curr_op} output {curr_rows:,}"
                    f" rows from {next_rows:,} input"
                    " rows. Check join keys for"
                    " unintended fanout."
                )

    return {
        "caller": caller,
        "action": action,
        "elapsed_seconds": elapsed,
        "status": "success",
        "jobs": len(evt.get("job_ids", [])),
        "stages": len(stages),
        "total_tasks": sum(
            s.get("tasks_total", 0) for s in stages
        ),
        "total_failed": total_failed,
        "findings": findings,
    }


def _cross_action_findings(actions):
    """Findings that require looking across all actions."""
    findings = []

    successful = [
        a for a in actions if a["status"] == "success"
    ]

    if not successful:
        return findings

    # Identify the bottleneck
    slowest = max(successful, key=lambda a: a["elapsed_seconds"])
    total_time = sum(a["elapsed_seconds"] for a in successful)

    if total_time > 0:
        pct = slowest["elapsed_seconds"] / total_time * 100
        if pct > 50 and len(successful) > 1:
            findings.append(
                f"BOTTLENECK: {slowest['caller']} ->"
                f" {slowest['action']} took"
                f" {slowest['elapsed_seconds']}s"
                f" ({pct:.0f}% of total pipeline time)."
                " Focus optimization here first."
            )

    # Check for many small actions (chatty pattern)
    short_actions = [
        a for a in successful
        if a["elapsed_seconds"] < 1.0
    ]
    if len(short_actions) > 5:
        findings.append(
            f"CHATTY: {len(short_actions)} actions"
            " completed in under 1 second each."
            " Consider combining them or caching"
            " intermediate results."
        )

    return findings


# --------------------------------------------------
# Cross-run comparison
# --------------------------------------------------

def compare(baseline_log, current_log):
    """Compare two runs and surface regressions.

    Args:
        baseline_log: iterable of strings (the "good" run)
        current_log: iterable of strings (the run to check)

    Returns:
        list of human-readable findings about regressions,
        new failures, and config drift.

    Usage:
        with open("baseline.log") as b, open("current.log") as c:
            for finding in spark_obs.compare(b, c):
                print(finding)
    """
    baseline = analyze(baseline_log)
    current = analyze(current_log)

    findings = []

    # Index by caller+action for matching
    base_actions = {
        (a["caller"], a["action"]): a
        for a in baseline["actions"]
    }

    for action in current["actions"]:
        key = (action["caller"], action["action"])
        base = base_actions.get(key)
        if not base:
            continue

        # Timing regression
        if base["elapsed_seconds"] > 0:
            ratio = (
                action["elapsed_seconds"]
                / base["elapsed_seconds"]
            )
            if ratio > 2.0:
                findings.append(
                    f"REGRESSION: {action['caller']} ->"
                    f" {action['action']} took"
                    f" {action['elapsed_seconds']}s,"
                    f" up from {base['elapsed_seconds']}s"
                    f" ({ratio:.1f}x slower)."
                )
            elif ratio < 0.5:
                findings.append(
                    f"IMPROVEMENT: {action['caller']} ->"
                    f" {action['action']} took"
                    f" {action['elapsed_seconds']}s,"
                    f" down from"
                    f" {base['elapsed_seconds']}s"
                    f" ({1/ratio:.1f}x faster)."
                )

        # New failures
        if (
            action["total_failed"] > 0
            and base["total_failed"] == 0
        ):
            findings.append(
                f"NEW FAILURES: {action['caller']} ->"
                f" {action['action']} had"
                f" {action['total_failed']} task"
                " failures that weren't present in"
                " the baseline run."
            )

        # Resolved failures
        if (
            action["total_failed"] == 0
            and base["total_failed"] > 0
        ):
            findings.append(
                f"RESOLVED: {action['caller']} ->"
                f" {action['action']} had"
                f" {base['total_failed']} task failures"
                " in baseline, now has none."
            )

    # New actions not in baseline
    for action in current["actions"]:
        key = (action["caller"], action["action"])
        if key not in base_actions:
            findings.append(
                f"NEW ACTION: {action['caller']} ->"
                f" {action['action']}"
                f" ({action['elapsed_seconds']}s)"
                " not present in baseline."
            )

    # Removed actions
    current_keys = {
        (a["caller"], a["action"])
        for a in current["actions"]
    }
    for key in base_actions:
        if key not in current_keys:
            findings.append(
                f"REMOVED ACTION: {key[0]} -> {key[1]}"
                " was in baseline but not in current run."
            )

    # Config drift
    if baseline["config"] and current["config"]:
        for key in set(
            list(baseline["config"].keys())
            + list(current["config"].keys())
        ):
            old = baseline["config"].get(key)
            new = current["config"].get(key)
            if old != new:
                findings.append(
                    f"CONFIG DRIFT: {key} changed"
                    f" from '{old}' to '{new}'."
                )

    return findings


# --------------------------------------------------
# Tabular export
# --------------------------------------------------

def to_records(log_lines):
    """Flatten spark_obs logs into tabular records.

    Returns a list of dicts, one per stage per action,
    suitable for export to CSV, Snowflake, pandas, etc.

    Args:
        log_lines: iterable of strings (raw log lines)

    Returns:
        list of flat dicts with one row per stage.

    Usage:
        import csv

        with open("driver.log") as f:
            records = spark_obs.to_records(f)

        with open("metrics.csv", "w", newline="") as out:
            writer = csv.DictWriter(
                out, fieldnames=records[0].keys()
            )
            writer.writeheader()
            writer.writerows(records)

        # Or with pandas:
        import pandas as pd
        df = pd.DataFrame(records)
    """
    events = _parse_events(log_lines)
    records = []

    for evt in events:
        if evt.get("event") != "action_complete":
            continue

        base = {
            "caller": evt.get("caller"),
            "action": evt.get("action"),
            "elapsed_seconds": evt.get("elapsed_seconds"),
            "num_jobs": len(evt.get("job_ids", [])),
        }

        stages = evt.get("stages", [])

        if not stages:
            records.append(base)
            continue

        for stage in stages:
            record = {
                **base,
                "stage_id": stage.get("stage_id"),
                "tasks_total": stage.get("tasks_total"),
                "tasks_completed": stage.get(
                    "tasks_completed"
                ),
                "tasks_failed": stage.get("tasks_failed"),
            }

            tm = stage.get("task_metrics", {})
            for metric_name in [
                "duration_ms",
                "shuffle_read_bytes",
                "shuffle_write_bytes",
                "records_read",
            ]:
                dist = tm.get(metric_name, {})
                for stat in [
                    "min", "p50", "p95", "max",
                ]:
                    col = f"{metric_name}_{stat}"
                    record[col] = dist.get(stat)

            records.append(record)

    return records