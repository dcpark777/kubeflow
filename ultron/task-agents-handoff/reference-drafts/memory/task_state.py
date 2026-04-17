"""
Task memory: per-task state directory.

Each task has its own directory containing state files the agent reads
at the start of each run and updates at the end. This gives tasks
continuity across multiple runs — iterate on the same task, resume
interrupted work, build on prior outputs.

Directory layout (per task):

    tasks/<task_id>/
      ├── task.md           # The task description (stable)
      ├── state.md          # Current state: what's done, what's open
      ├── history.md        # Append-only log of runs
      ├── artifacts/        # Files produced by runs
      └── refine_log.md     # Append-only log of refinement turns

The memory module provides:
- `TaskState.create(...)` — initialize a new task directory
- `TaskState.load(task_id)` — read an existing task
- `.render_for_agent()` — produce the memory context to inject into
  the system prompt
- `.append_run_summary(...)` — called after execution to update state
- `.append_refine_turn(...)` — called after each refine turn

State is markdown files, not JSON. This is deliberate: agents read
markdown better than JSON, and your users can inspect / edit state
by hand when debugging.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


# The root where all task directories live. Configure via env var or
# pass explicitly; this is the default.
DEFAULT_TASKS_ROOT = Path.home() / ".task-agents" / "tasks"


@dataclass
class TaskState:
    task_id: str
    root: Path

    @property
    def task_dir(self) -> Path:
        return self.root / self.task_id

    @property
    def task_file(self) -> Path:
        return self.task_dir / "task.md"

    @property
    def state_file(self) -> Path:
        return self.task_dir / "state.md"

    @property
    def history_file(self) -> Path:
        return self.task_dir / "history.md"

    @property
    def refine_log_file(self) -> Path:
        return self.task_dir / "refine_log.md"

    @property
    def artifacts_dir(self) -> Path:
        return self.task_dir / "artifacts"

    # ---- Construction ----

    @classmethod
    def create(
        cls,
        task_id: str,
        task_description: str,
        *,
        root: Path = DEFAULT_TASKS_ROOT,
        label: str | None = None,
    ) -> "TaskState":
        """
        Initialize a new task directory. Overwrites if one exists at
        this task_id — callers should ensure uniqueness.
        """
        state = cls(task_id=task_id, root=root)
        state.task_dir.mkdir(parents=True, exist_ok=True)
        state.artifacts_dir.mkdir(exist_ok=True)

        label_line = f"**Type:** {label}\n\n" if label else ""
        state.task_file.write_text(
            f"# Task: {task_id}\n\n"
            f"{label_line}"
            f"## Description\n\n"
            f"{task_description}\n",
            encoding="utf-8",
        )
        state.state_file.write_text(
            "# State\n\n"
            "_No runs yet. This file is updated after each execution._\n\n"
            "## Current status\n\nNot started.\n\n"
            "## Key findings\n\n_None yet._\n\n"
            "## Open questions\n\n_None yet._\n\n"
            "## What NOT to try again\n\n_None yet._\n",
            encoding="utf-8",
        )
        state.history_file.write_text(
            "# Run history\n\n_Append-only log of executions._\n",
            encoding="utf-8",
        )
        state.refine_log_file.write_text(
            "# Refinement log\n\n_Append-only log of refinement turns._\n",
            encoding="utf-8",
        )
        return state

    @classmethod
    def load(
        cls,
        task_id: str,
        *,
        root: Path = DEFAULT_TASKS_ROOT,
    ) -> "TaskState":
        state = cls(task_id=task_id, root=root)
        if not state.task_dir.exists():
            raise FileNotFoundError(f"No task at {state.task_dir}")
        return state

    def delete(self) -> None:
        """Remove the entire task directory. Irreversible."""
        if self.task_dir.exists():
            shutil.rmtree(self.task_dir)

    # ---- Reading ----

    def render_for_agent(self, *, include_history: bool = False) -> str:
        """
        Render the task's memory as markdown for injection into the
        agent's system prompt or initial user message.

        By default, includes task description, current state, and
        refine log. History (full prior-run summaries) is excluded
        unless requested — it's usually redundant with state.md and
        adds tokens.
        """
        parts: list[str] = []
        parts.append("# Task context (memory)\n")
        parts.append(
            "You are working on an existing task. The following is what's "
            "known so far. Build on this — don't start from scratch, and "
            "don't repeat work that's already been done.\n"
        )

        if self.task_file.exists():
            parts.append(self.task_file.read_text(encoding="utf-8"))

        if self.state_file.exists():
            parts.append(self.state_file.read_text(encoding="utf-8"))

        if self.refine_log_file.exists():
            refine_content = self.refine_log_file.read_text(encoding="utf-8")
            # Only include if there's actual content beyond the header
            if len(refine_content.strip().splitlines()) > 3:
                parts.append(refine_content)

        if include_history and self.history_file.exists():
            parts.append(self.history_file.read_text(encoding="utf-8"))

        return "\n\n---\n\n".join(parts)

    # ---- Writing ----

    def append_run_summary(
        self,
        *,
        summary: str,
        findings: str = "",
        open_questions: str = "",
        avoid_list: str = "",
    ) -> None:
        """
        Called after a run finishes. Appends to history and replaces
        the current state.

        The summary should be written by the agent that just ran —
        ask it to produce these fields as part of its output contract
        (the profiles already ask for a summary; add a structured
        state update for tasks with memory enabled).
        """
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # Append to history (never rewritten)
        history_entry = (
            f"\n## Run {timestamp}\n\n"
            f"{summary}\n"
        )
        self._append(self.history_file, history_entry)

        # Replace state (always current)
        state_content = (
            f"# State\n\n"
            f"_Last updated: {timestamp}_\n\n"
            f"## Current status\n\n{summary}\n\n"
            f"## Key findings\n\n"
            f"{findings if findings else '_None yet._'}\n\n"
            f"## Open questions\n\n"
            f"{open_questions if open_questions else '_None yet._'}\n\n"
            f"## What NOT to try again\n\n"
            f"{avoid_list if avoid_list else '_None yet._'}\n"
        )
        self.state_file.write_text(state_content, encoding="utf-8")

    def append_refine_turn(
        self,
        *,
        user_message: str,
        agent_response: str,
    ) -> None:
        """Append a single refinement turn to the refine log."""
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        entry = (
            f"\n## Turn {timestamp}\n\n"
            f"**User:** {user_message}\n\n"
            f"**Agent:** {agent_response}\n"
        )
        self._append(self.refine_log_file, entry)

    def update_task_description(self, new_description: str) -> None:
        """
        Called when refinement produces a sharpened task description.
        Replaces the task file; the refine_log preserves the history
        of how it evolved.
        """
        content = self.task_file.read_text(encoding="utf-8")
        # Replace everything after "## Description"
        marker = "## Description"
        if marker in content:
            prefix = content.split(marker)[0]
            self.task_file.write_text(
                f"{prefix}{marker}\n\n{new_description}\n",
                encoding="utf-8",
            )
        else:
            self.task_file.write_text(
                f"# Task: {self.task_id}\n\n"
                f"## Description\n\n{new_description}\n",
                encoding="utf-8",
            )

    def save_artifact(self, filename: str, content: str) -> Path:
        """Save a file into the task's artifacts directory."""
        path = self.artifacts_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    # ---- Helpers ----

    @staticmethod
    def _append(path: Path, content: str) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(content)
