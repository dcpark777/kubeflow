"""
Quick eval harness for the model selector.

Tests the selector against labeled cases where we have strong opinions
about what it should pick. Looser than the classifier's eval — the
right tier is genuinely debatable for many tasks, so we check that
the selector stays in a reasonable band rather than hitting an exact
answer.

Usage:
    python -m model_selector.test_selector
"""
from __future__ import annotations

from dataclasses import dataclass

from select_model import Label, Mode, select_model


@dataclass
class TestCase:
    description: str
    label: Label
    mode: Mode
    # Tiers we'd accept as reasonable. Usually a contiguous range
    # (e.g., {"sonnet", "opus"} means "don't pick haiku for this").
    acceptable_tiers: set[str]
    # Note about what's being tested
    note: str


TIER_ORDER = ["haiku", "sonnet", "opus"]


TEST_CASES = [
    # --- Haiku-appropriate ---
    TestCase(
        "Rename the variable `foo` to `bar` in config.py",
        label="coding",
        mode="execute",
        acceptable_tiers={"haiku"},
        note="trivially bounded coding — should be haiku",
    ),
    TestCase(
        "Ideas for what to name our internal deploy tool",
        label="brainstorming",
        mode="execute",
        acceptable_tiers={"haiku", "sonnet"},
        note="short brainstorm, variety over depth",
    ),
    # --- Sonnet-appropriate ---
    TestCase(
        "Add a retry-with-backoff decorator to the Snowflake client",
        label="coding",
        mode="execute",
        acceptable_tiers={"sonnet"},
        note="moderate coding, clear scope",
    ),
    TestCase(
        "Plan a one-week spike to evaluate a vector store for our search",
        label="planning",
        mode="execute",
        acceptable_tiers={"sonnet"},
        note="short planning, well-scoped",
    ),
    # --- Opus-appropriate ---
    TestCase(
        "Migrate our four batch model repos from the old Airflow setup "
        "to the new Jenkins CI/CD system across Q2 and Q3",
        label="planning",
        mode="execute",
        acceptable_tiers={"opus"},
        note="multi-quarter, multi-repo, high stakes",
    ),
    TestCase(
        "Compare Flink vs Spark Structured Streaming for our fraud "
        "velocity features across latency, cost, operational overhead, "
        "and team skill fit",
        label="research",
        mode="execute",
        acceptable_tiers={"sonnet", "opus"},
        note="multi-dimensional synthesis",
    ),
    TestCase(
        "Debug why our feature store is silently dropping 0.2% of writes "
        "under load — root cause is unknown, could be in Kafka, Spark, "
        "or the Redis sink",
        label="coding",
        mode="execute",
        acceptable_tiers={"opus"},
        note="thorny debugging, unknown root cause",
    ),
    # --- Refine mode: should stay modest ---
    TestCase(
        "Migrate our batch model repos to Jenkins",  # same task, refine mode
        label="planning",
        mode="refine",
        acceptable_tiers={"sonnet"},
        note="refine mode — sonnet even for big tasks",
    ),
    TestCase(
        "Help me sharpen this task: redesign our inference logging pipeline",
        label="coding",
        mode="refine",
        acceptable_tiers={"sonnet"},
        note="refine is conversation, not execution",
    ),
]


def run() -> None:
    passes = 0
    fails = 0
    for i, case in enumerate(TEST_CASES, 1):
        result = select_model(
            task_description=case.description,
            label=case.label,
            mode=case.mode,
        )

        got = result.tier
        if got in case.acceptable_tiers:
            status = "PASS"
            passes += 1
        else:
            status = f"FAIL (want {sorted(case.acceptable_tiers)})"
            fails += 1

        preview = case.description[:55] + (
            "..." if len(case.description) > 55 else ""
        )
        print(
            f"{i:2d}. [{status}] tier={got:6s} thinking={result.thinking:8s} "
            f"| {case.note}"
        )
        print(f"     task: {preview}")
        print(f"     reason: {result.reason}")

    print()
    print(f"Passed: {passes}/{len(TEST_CASES)}")
    if fails:
        print(f"Failed: {fails}")


if __name__ == "__main__":
    run()
