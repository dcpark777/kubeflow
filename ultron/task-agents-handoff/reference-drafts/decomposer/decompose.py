"""
Task decomposer.

Given a task description, determines if it's one task or a compound
task that should be split into sub-tasks.

Usage:
    from decompose import decompose_task

    result = decompose_task("Research vector DBs and write migration plan")
    # CompoundResult(subtasks=[...])

    if isinstance(result, SingleResult):
        # Route the one task through the pipeline
        ...
    elif isinstance(result, CompoundResult):
        # Route each sub-task independently, respecting dependencies
        for subtask in result.subtasks:
            ...
    else:  # UnclearResult
        # Ask user
        ...
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from anthropic import Anthropic

DECOMPOSER_MODEL = "claude-haiku-4-5-20251001"
PROMPT_PATH = Path(__file__).parent / "decomposer-prompt.md"


@dataclass(frozen=True)
class Subtask:
    name: str
    description: str
    depends_on: tuple[int, ...] = ()


@dataclass(frozen=True)
class SingleResult:
    type: str = "single"


@dataclass(frozen=True)
class CompoundResult:
    subtasks: tuple[Subtask, ...]
    type: str = "compound"


@dataclass(frozen=True)
class UnclearResult:
    reason: str = ""
    type: str = "unclear"


DecomposeResult = SingleResult | CompoundResult | UnclearResult


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def decompose_task(
    task_description: str,
    *,
    client: Anthropic | None = None,
) -> DecomposeResult:
    """
    Decide if the task is single, compound, or ambiguous.

    Falls back to single on malformed output — treating as single is
    safer than failing the request or asking the user spuriously.
    """
    client = client or Anthropic()

    response = client.messages.create(
        model=DECOMPOSER_MODEL,
        max_tokens=1000,  # compound outputs can be substantial
        system=_load_system_prompt(),
        messages=[{"role": "user", "content": task_description}],
    )

    raw = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()

    return _parse_decomposer_output(raw)


def _parse_decomposer_output(raw: str) -> DecomposeResult:
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return SingleResult()

    task_type = parsed.get("type")

    if task_type == "single":
        return SingleResult()

    if task_type == "unclear":
        reason = parsed.get("reason", "")
        return UnclearResult(reason=reason if isinstance(reason, str) else "")

    if task_type == "compound":
        raw_subtasks = parsed.get("subtasks", [])
        if not isinstance(raw_subtasks, list) or not raw_subtasks:
            return SingleResult()

        subtasks = []
        for item in raw_subtasks:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            description = item.get("description", "")
            depends_on = item.get("depends_on", [])
            if not name or not description:
                continue
            if not isinstance(depends_on, list) or not all(
                isinstance(d, int) for d in depends_on
            ):
                depends_on = []
            subtasks.append(
                Subtask(
                    name=name,
                    description=description,
                    depends_on=tuple(depends_on),
                )
            )

        if len(subtasks) < 2:
            # "Compound" with fewer than 2 valid sub-tasks is really single
            return SingleResult()

        return CompoundResult(subtasks=tuple(subtasks))

    # Unknown type
    return SingleResult()
