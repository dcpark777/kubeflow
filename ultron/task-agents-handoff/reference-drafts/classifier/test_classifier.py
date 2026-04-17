"""
Quick eval harness for the task classifier.

Run this to verify the classifier is behaving reasonably before trusting
it in your app. Expand the test cases over time based on real tasks
you see come through.

Usage:
    python -m classifier.test_classifier

Prints one line per test case and a summary at the end.
"""
from __future__ import annotations

from dataclasses import dataclass

from classify import classify_task


@dataclass
class TestCase:
    description: str
    expected_label: str
    # If True, "unclear" is also an acceptable answer for this case
    unclear_ok: bool = False


# Deliberately mixed: easy cases, edge cases, and a few traps where
# surface vocabulary misleads.
TEST_CASES = [
    # --- Clear planning ---
    TestCase(
        "Migrate our four batch model repos from the old Airflow setup "
        "to the new Jenkins-based CI/CD system",
        expected_label="planning",
    ),
    TestCase(
        "Roadmap for launching the fraud scoring API to production over "
        "the next quarter",
        expected_label="planning",
    ),
    # --- Clear brainstorming ---
    TestCase(
        "What are some ways we could make the data scientist onboarding "
        "flow less painful",
        expected_label="brainstorming",
    ),
    TestCase(
        "Help me think of names for our new ML observability tool",
        expected_label="brainstorming",
    ),
    # --- Clear coding ---
    TestCase(
        "Fix the off-by-one error in the pagination logic in search.py",
        expected_label="coding",
    ),
    TestCase(
        "Add retry-with-backoff to the Snowflake connector in kubekit",
        expected_label="coding",
    ),
    # --- Clear research ---
    TestCase(
        "Compare Parquet vs the Snowflake Spark connector for large "
        "time-range fraud feature scans",
        expected_label="research",
    ),
    TestCase(
        "What are the tradeoffs between Flink and Spark Structured "
        "Streaming for fraud velocity features",
        expected_label="research",
    ),
    # --- Traps: surface vocabulary misleads ---
    TestCase(
        # Uses "plan" but is really a coding task
        "Plan a refactor of the feature engineering pipeline — I just "
        "want to rename the base classes and split the file",
        expected_label="coding",
        unclear_ok=True,  # this is genuinely borderline
    ),
    TestCase(
        # Uses "research" but ends in a plan
        "Research what it would take to migrate us off Airflow and give "
        "me a phased migration plan",
        expected_label="planning",
        unclear_ok=True,
    ),
    # --- Should land as unclear ---
    TestCase(
        "Help me with the auth system",
        expected_label="unclear",
    ),
    TestCase(
        "Something's off with the fraud pipeline, can you take a look",
        expected_label="unclear",
    ),
]


def run() -> None:
    passes = 0
    fails = 0
    for i, case in enumerate(TEST_CASES, 1):
        result = classify_task(case.description)
        got = result.label

        if got == case.expected_label:
            status = "PASS"
            passes += 1
        elif case.unclear_ok and got == "unclear":
            status = "PASS (unclear ok)"
            passes += 1
        else:
            status = f"FAIL (expected {case.expected_label})"
            fails += 1

        preview = case.description[:60] + (
            "..." if len(case.description) > 60 else ""
        )
        print(f"{i:2d}. [{status}] got={got:13s} | {preview}")

    print()
    print(f"Passed: {passes}/{len(TEST_CASES)}")
    if fails:
        print(f"Failed: {fails}")


if __name__ == "__main__":
    run()
