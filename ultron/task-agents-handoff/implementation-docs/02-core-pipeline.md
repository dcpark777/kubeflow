# 02 — Core pipeline

The pipeline is the only module that knows about all the others. It
composes them into two top-level functions the app calls:

- `handle_new_task_submission(description)` — called when a user
  creates a task. Runs decomposition, then for the single or compound
  case, runs the routing pipeline and returns a dispatch payload.
- `finalize_execution(...)` — called after Claude Code finishes. Runs
  critique (if applicable), triggers revision (if flagged), extracts
  state, writes to memory.

Also:

- `prepare_task_for_execution(description, *, task_id, mode, ...)` —
  the inner function that handles a single task. Used for both
  sub-tasks and refinement.
- `handle_refine_turn(task_id, user_message, agent_response)` — called
  after each refinement turn to append to the task's refine log.

Build this last. All other modules must exist first.

## File

`task_agents/pipeline.py`

## Dependencies

```python
from task_agents.classifier.classify import classify_task
from task_agents.decomposer.decompose import decompose_task
from task_agents.selector.select_model import select_model
from task_agents.critique.critique import (
    should_critique,
    critique_output,
    build_revision_prompt,
)
from task_agents.memory.task_state import TaskState
from task_agents.memory.extract_state import extract_state
from task_agents.types import (  # types
    ...
)
```

## Profile resolution

Profiles live in `task_agents/profiles/`. Resolve a label + mode to an
absolute path:

```python
from pathlib import Path

PROFILES_DIR = Path(__file__).parent / "profiles"

def resolve_profile(label: Label, mode: Mode) -> Path:
    path = PROFILES_DIR / f"{label}-{mode}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"No profile for {label}/{mode} at {path}. "
            f"Did you forget to author it?"
        )
    return path
```

The pipeline loads profile *content* (not just the path) when building
the dispatch payload — the app's runner shouldn't have to re-read the
file.

## `handle_new_task_submission`

Top-level entry for a new task. Handles decomposition first, then
routes single tasks through `prepare_task_for_execution`.

Logic:

1. Call `decompose_task(description)`.
2. If `UnclearDecomposition`, return `AskUserDecompositionPayload`.
3. If `SingleResult`, return `prepare_task_for_execution(description)`.
4. If `CompoundResult`:
   a. Generate a parent task ID. Create parent `TaskState` with label
      `"compound"` so it shows up in task lists but doesn't have an
      execution profile.
   b. For each sub-task, generate `{parent_id}--{slug(name)}` as the
      sub-task ID. Don't run `prepare_task_for_execution` here — the
      runner will call it per sub-task as dependencies resolve.
   c. Return `ExecuteCompoundPayload` with the sub-task plans. The
      runner owns dependency-ordering and per-sub-task dispatch.

## `prepare_task_for_execution`

The inner function. Handles a single task (or sub-task).

Signature:

```python
def prepare_task_for_execution(
    task_description: str,
    *,
    task_id: str | None = None,
    mode: Mode = "execute",
    parent_task_id: str | None = None,
    dependency_outputs: dict[str, str] | None = None,
) -> DispatchPayload:
```

Logic:

1. **Classify**. `classify_task(description)`. If uncertain, return
   `AskUserLabelPayload` immediately.
2. **Select model**. `select_model(description, label, mode)`.
3. **Resolve profile**. `resolve_profile(label, mode)`. Read its
   content into a string.
4. **Load or create memory**.
   - If `task_id is None`: generate one; create `TaskState`; memory
     context is empty.
   - Else: `TaskState.load(task_id)`; render memory context.
5. **Build dependency context** (for sub-tasks only). If
   `dependency_outputs` is provided, format as:
   ```
   # Context from prior sub-tasks

   ## {name_1}
   {output_1}

   ## {name_2}
   {output_2}
   ```
6. **Determine critique flag**. `should_critique(tier, label)`.
7. **Return ExecutePayload** with everything the runner needs.

## `finalize_execution`

Called after Claude Code finishes a task.

Signature:

```python
def finalize_execution(
    *,
    task_id: str,
    task_description: str,
    output: str,
    should_run_critique: bool,
    run_executor: Callable[[str], str] | None = None,
) -> FinalizeResult:
```

`run_executor` is a callback the app provides that takes a new user
message and runs the same task through Claude Code, returning the
output. The pipeline uses it to trigger revision without needing to
know how the app spawns Claude Code.

Logic:

1. Default `final_output = output`, `was_revised = False`,
   `critique_result = None`.
2. If `should_run_critique` and `run_executor is not None`:
   a. Call `critique_output(description, output)`.
   b. If verdict is `"revise"`:
      - Build revision prompt via `build_revision_prompt(output, guidance)`.
      - Call `run_executor(revision_prompt)` to get revised output.
      - Set `final_output = revised`, `was_revised = True`.
3. **Update memory**:
   - `TaskState.load(task_id)`.
   - `extract_state(description, final_output)` → dict with summary,
     findings, open_questions, avoid_list.
   - `state.append_run_summary(**extracted)`.
   - If the task doesn't exist (caller's error or task wasn't
     registered), log a warning but don't raise.
4. Return:

```python
@dataclass(frozen=True)
class FinalizeResult:
    output: str
    was_revised: bool
    critique_issues: tuple[Issue, ...]
```

## `handle_refine_turn`

Called after each round of the refinement chat.

Signature:

```python
def handle_refine_turn(
    task_id: str,
    user_message: str,
    agent_response: str,
    *,
    new_task_description: str | None = None,
) -> None:
```

Logic:

1. `TaskState.load(task_id)`.
2. `state.append_refine_turn(user_message, agent_response)`.
3. If `new_task_description` is provided, `state.update_task_description(new)`.

The refine chat itself is handled by the app's existing chat UI. This
function is just the hook that lets the pipeline track what happened.
The app should call it after each turn; the refinement profile's
output contract (see profile docs) produces a new task description
as part of its final turn — that's what gets passed as
`new_task_description`.

## Invariant: dispatch payload integrity

The app's runner should be able to dispatch an `ExecutePayload`
without calling back into the pipeline for more context. Everything
it needs is in the payload:

- Model args for launching Claude Code
- The profile content (not just the path — though the path is there
  for debugging)
- The memory context as a ready-to-inject markdown string
- The dependency context similarly

The pipeline reads files; the runner consumes strings. This keeps
the runner simple and makes it easy to swap in other execution
backends later (direct API, a sandboxed container, etc.).

## Error handling

Routing-layer failures are handled inside those layers (fail-safe
defaults). Pipeline-level failures to handle:

- `resolve_profile` raising `FileNotFoundError` — this is a
  configuration bug (missing profile file). Surface it clearly; the
  app operator needs to know.
- `TaskState.load` raising `FileNotFoundError` — either the task was
  deleted or the ID is wrong. Log and return a payload that asks the
  app to handle recovery (e.g., redirect to task creation).
- `run_executor` callback raising — let it propagate. Revision
  failures should surface to the user.

Don't wrap everything in try/except. The routing layers already handle
LLM failures. The pipeline should let real errors be real errors.

## What the pipeline does NOT do

- **Does not call Claude Code.** The app's runner does that. The
  pipeline only prepares payloads and consumes outputs.
- **Does not handle sub-task dependency sequencing.** The runner
  owns this. The compound payload tells the runner what depends
  on what; the runner is responsible for running them in order and
  passing earlier outputs to later sub-tasks.
- **Does not render UI.** All user-facing text is the app's concern.
  The pipeline returns structured data.
