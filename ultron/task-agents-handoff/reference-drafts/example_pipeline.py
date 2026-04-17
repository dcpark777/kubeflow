"""
End-to-end pipeline example.

Shows the full flow:

    1. Decompose  — is this one task or several?
    2. For each (sub)task:
       a. Classify  — task type label
       b. Select    — model tier + thinking
       c. Resolve   — profile file
       d. Memory    — load or create task state
       e. Execute   — (handled by caller: launch Claude Code)
       f. Critique  — review output, optionally revise
       g. Update    — write run summary to task memory

The actual execution step is marked — this is where your app's
dispatcher launches Claude Code with the computed args + profile +
memory context. This file shows the decision flow around it.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
for subdir in ("classifier", "model-selector", "decomposer", "memory", "critique"):
    sys.path.insert(0, str(ROOT / subdir))

from classify import classify_task, resolve_profile  # noqa: E402
from critique import (  # noqa: E402
    build_revision_prompt,
    critique_output,
    should_critique,
)
from decompose import (  # noqa: E402
    CompoundResult,
    SingleResult,
    UnclearResult,
    decompose_task,
)
from extract_state import extract_state  # noqa: E402
from select_model import select_model  # noqa: E402
from task_state import TaskState  # noqa: E402


# ---------------------------------------------------------------------------
# Pipeline for a single (sub)task
# ---------------------------------------------------------------------------


def prepare_task_for_execution(
    task_description: str,
    *,
    task_id: str | None = None,
    mode: str = "execute",
    parent_task_id: str | None = None,
    dependency_outputs: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Run the full pre-execution pipeline for one task.

    Returns a dispatch payload the app's runner uses to launch Claude
    Code. Does NOT execute the task itself — that's the caller's job,
    because execution is async, long-running, and UI-dependent.

    Args:
        task_description: The task text.
        task_id: If None, a new one is generated and the task gets
            fresh memory. If provided, existing memory is loaded.
        mode: "execute" or "refine".
        parent_task_id: Set when this is a sub-task of a decomposed
            compound task.
        dependency_outputs: Set when this sub-task depends on earlier
            sub-tasks' outputs (from decomposition).
    """
    # 1. Classify
    classification = classify_task(task_description)
    if classification.uncertain:
        return {
            "action": "ask_user_label",
            "candidates": classification.candidates,
            "task_description": task_description,
        }
    label = classification.label

    # 2. Select model
    selection = select_model(
        task_description=task_description,
        label=label,
        mode=mode,  # type: ignore[arg-type]
    )

    # 3. Resolve profile
    profile_path = resolve_profile(label, mode=mode)  # type: ignore[arg-type]

    # 4. Load or create task memory
    if task_id is None:
        task_id = _generate_task_id(task_description)
        state = TaskState.create(
            task_id=task_id,
            task_description=task_description,
            label=label,
        )
        memory_context = ""  # New task, no prior memory
    else:
        state = TaskState.load(task_id)
        memory_context = state.render_for_agent()

    # 5. Build dependency context if this is a sub-task
    dependency_context = ""
    if dependency_outputs:
        dependency_context = _format_dependencies(dependency_outputs)

    # 6. Dispatch payload — app's runner launches Claude Code with these
    return {
        "action": "execute",
        "task_id": task_id,
        "parent_task_id": parent_task_id,
        "label": label,
        "mode": mode,
        "profile_path": str(profile_path),
        "model_tier": selection.tier,
        "thinking": selection.thinking,
        "selection_reason": selection.reason,
        "claude_code_args": selection.to_claude_code_args(),
        # Context to inject alongside the system prompt / as first user message
        "memory_context": memory_context,
        "dependency_context": dependency_context,
        # Hint to post-execution handler
        "should_run_critique": should_critique(
            selection_tier=selection.tier,
            label=label,
        ),
    }


def handle_new_task_submission(task_description: str) -> dict[str, Any]:
    """
    Entry point when a user submits a task.

    First checks if it's compound; if so, prepares each sub-task.
    If single, prepares the one task directly.
    """
    # 0. Decompose first
    decomp = decompose_task(task_description)

    if isinstance(decomp, UnclearResult):
        return {
            "action": "ask_user_decomposition",
            "reason": decomp.reason,
            "task_description": task_description,
        }

    if isinstance(decomp, SingleResult):
        return prepare_task_for_execution(task_description)

    # Compound case — prepare sub-tasks, preserving dependency structure
    assert isinstance(decomp, CompoundResult)

    # Create a parent task to track the compound as a whole
    parent_id = _generate_task_id(task_description)
    TaskState.create(
        task_id=parent_id,
        task_description=task_description,
        label="compound",
    )

    subtask_plans = []
    subtask_ids = []
    for subtask in decomp.subtasks:
        sub_id = f"{parent_id}--{_slug(subtask.name)}"
        subtask_ids.append(sub_id)
        # Note: we don't execute here — the dispatcher handles
        # dependency ordering and runs them in sequence/parallel as
        # appropriate based on depends_on
        subtask_plans.append(
            {
                "subtask_id": sub_id,
                "name": subtask.name,
                "description": subtask.description,
                "depends_on_indices": list(subtask.depends_on),
            }
        )

    return {
        "action": "execute_compound",
        "parent_task_id": parent_id,
        "subtask_plans": subtask_plans,
    }


# ---------------------------------------------------------------------------
# Post-execution: critique + memory update
# ---------------------------------------------------------------------------


def finalize_execution(
    *,
    task_id: str,
    task_description: str,
    output: str,
    run_critique: bool,
    run_executor: Any = None,  # Callable that re-runs the task with a revision prompt
) -> dict[str, Any]:
    """
    Called after an execution completes.

    Optionally runs critique; if critique says 'revise' and the caller
    provided a run_executor, runs a single revision pass. Then writes
    the run summary into task memory.

    Returns the final output to show the user, plus metadata.
    """
    final_output = output
    critique_result = None
    was_revised = False

    if run_critique:
        critique_result = critique_output(task_description, output)
        if critique_result.verdict == "revise" and run_executor is not None:
            revision_prompt = build_revision_prompt(
                original_output=output,
                guidance=critique_result.revision_guidance,
            )
            final_output = run_executor(revision_prompt)
            was_revised = True

    # Update memory
    try:
        state = TaskState.load(task_id)
        state_fields = extract_state(
            task_description=task_description,
            output=final_output,
        )
        state.append_run_summary(**state_fields)
    except FileNotFoundError:
        # Task wasn't tracked — not fatal, just log and continue
        pass

    return {
        "output": final_output,
        "was_revised": was_revised,
        "critique_issues": (
            [
                {"severity": i.severity, "description": i.description}
                for i in (critique_result.issues if critique_result else ())
            ]
            if critique_result
            else []
        ),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _generate_task_id(description: str) -> str:
    """Short, stable-ish ID combining a slug and a random suffix."""
    return f"{_slug(description)[:40]}--{uuid.uuid4().hex[:8]}"


def _slug(text: str) -> str:
    return "".join(
        c if c.isalnum() or c == "-" else "-" for c in text.lower()
    ).strip("-")


def _format_dependencies(deps: dict[str, str]) -> str:
    parts = ["# Context from prior sub-tasks\n"]
    for name, output in deps.items():
        parts.append(f"## {name}\n\n{output}")
    return "\n\n".join(parts)


def _truncate(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20] + "\n\n[...truncated]"


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    demo_tasks = [
        # Single simple task
        "Rename `foo` to `bar` in config.py",
        # Single complex task
        "Migrate our batch pipelines from Airflow to a Jenkins-based CI/CD "
        "system across four repos over Q2-Q3",
        # Compound task
        "Research vector database options, pick one, and write a migration "
        "plan for moving our search off Elasticsearch",
    ]

    for task in demo_tasks:
        print(f"\n{'=' * 70}")
        print(f"Task: {task}")
        print("-" * 70)
        result = handle_new_task_submission(task)
        print(f"Action: {result['action']}")
        for k, v in result.items():
            if k == "action":
                continue
            if isinstance(v, str) and len(v) > 100:
                v = v[:100] + "..."
            print(f"  {k}: {v}")
