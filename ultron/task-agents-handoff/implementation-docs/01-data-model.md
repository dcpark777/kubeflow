# 01 — Data model

Build this first. Every other module depends on these types.

## Package layout

Recommend a single `task_agents/` package with submodules:

```
task_agents/
├── __init__.py          # re-exports the public API
├── types.py             # everything in this doc
├── classifier/
│   ├── __init__.py
│   ├── classify.py
│   ├── classifier-prompt.md
│   └── test_classifier.py
├── decomposer/
│   ├── __init__.py
│   ├── decompose.py
│   ├── decomposer-prompt.md
│   └── test_decomposer.py
├── selector/
│   ├── __init__.py
│   ├── select_model.py
│   ├── selector-prompt.md
│   └── test_selector.py
├── memory/
│   ├── __init__.py
│   ├── task_state.py
│   ├── extract_state.py
│   └── test_memory.py
├── critique/
│   ├── __init__.py
│   ├── critique.py
│   ├── critique-prompt.md
│   └── test_critique.py
├── profiles/            # markdown content (see 04)
└── skills/              # markdown content (see 04)
```

## Core enums

In `task_agents/types.py`:

```python
from typing import Literal

Label = Literal["planning", "brainstorming", "coding", "research"]
LabelOrUnclear = Literal["planning", "brainstorming", "coding", "research", "unclear"]
Tier = Literal["haiku", "sonnet", "opus"]
Thinking = Literal["off", "adaptive", "high"]
Mode = Literal["execute", "refine"]
Verdict = Literal["pass", "revise"]
Severity = Literal["major", "minor"]
```

Use `LabelOrUnclear` only at the classifier boundary and anywhere that
handles pre-classification routing. Everything downstream should take
`Label` — the pipeline ensures unclear is resolved before reaching
those layers.

## Result types

All routing layers return frozen dataclasses, not dicts. Makes the
contract explicit and enables pattern matching in the pipeline.

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ClassificationResult:
    label: LabelOrUnclear
    uncertain: bool
    candidates: tuple[str, ...] | None = None

@dataclass(frozen=True)
class SelectionResult:
    tier: Tier
    thinking: Thinking
    reason: str

    def to_claude_code_args(self) -> list[str]: ...
    def to_api_params(self) -> dict: ...

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
class UnclearDecomposition:
    reason: str = ""
    type: str = "unclear"

DecomposeResult = SingleResult | CompoundResult | UnclearDecomposition

@dataclass(frozen=True)
class Issue:
    severity: Severity
    description: str

@dataclass(frozen=True)
class CritiqueResult:
    verdict: Verdict
    issues: tuple[Issue, ...]
    revision_guidance: str
```

## Task identity

Tasks need stable, unique IDs. The pipeline generates them from a
description slug + random suffix:

```python
import uuid

def generate_task_id(description: str) -> str:
    slug = _slug(description)[:40]
    return f"{slug}--{uuid.uuid4().hex[:8]}"
```

For compound sub-tasks, the ID format is `{parent_id}--{slug(subtask.name)}`.
This makes filesystem navigation meaningful for debugging.

## The dispatch payload

The pipeline's `prepare_task_for_execution` returns a TypedDict (or
dataclass if you prefer) that tells the app's runner everything it
needs to launch Claude Code:

```python
from typing import TypedDict

class ExecutePayload(TypedDict):
    action: Literal["execute"]
    task_id: str
    parent_task_id: str | None
    label: Label
    mode: Mode
    profile_path: str           # absolute path to profile .md
    model_tier: Tier
    thinking: Thinking
    selection_reason: str
    claude_code_args: list[str]  # ["--model", "opus", "--effort", "auto"]
    memory_context: str          # markdown string to inject
    dependency_context: str      # markdown string, or ""
    should_run_critique: bool

class AskUserLabelPayload(TypedDict):
    action: Literal["ask_user_label"]
    candidates: tuple[str, ...] | None
    task_description: str

class AskUserDecompositionPayload(TypedDict):
    action: Literal["ask_user_decomposition"]
    reason: str
    task_description: str

class ExecuteCompoundPayload(TypedDict):
    action: Literal["execute_compound"]
    parent_task_id: str
    subtask_plans: list["SubtaskPlan"]

class SubtaskPlan(TypedDict):
    subtask_id: str
    name: str
    description: str
    depends_on_indices: list[int]

DispatchPayload = (
    ExecutePayload
    | AskUserLabelPayload
    | AskUserDecompositionPayload
    | ExecuteCompoundPayload
)
```

The app's runner pattern-matches on `action` to decide what to do.
`ask_*` actions bubble up to the UI; `execute` and `execute_compound`
dispatch to the Claude Code launcher.

## Public API

What `task_agents/__init__.py` exports. Keep this surface small — the
whole point of the layered architecture is that the app doesn't need
to know about internals.

```python
from task_agents.pipeline import (
    prepare_task_for_execution,
    handle_new_task_submission,
    finalize_execution,
    handle_refine_turn,
)
from task_agents.types import (
    Label, Tier, Thinking, Mode,
    ClassificationResult, SelectionResult,
    DecomposeResult, CritiqueResult,
    DispatchPayload,
)
from task_agents.memory.task_state import TaskState
```

The app should need nothing else.
