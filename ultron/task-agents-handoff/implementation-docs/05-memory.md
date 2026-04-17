# 05 — Memory

Per-task state directory. Each task gets its own folder with markdown
files the agent reads at the start of each run and updates at the end.

Why markdown and not a database: agents read markdown better, the
files are inspectable by hand when debugging, and this composes with
git if the app wants to track task history. The downside is no query
layer — if you later want cross-task search, that's a separate index
you add, not a rewrite of the storage.

Two modules:

1. `memory/task_state.py` — the filesystem layer
2. `memory/extract_state.py` — the Haiku-based structured extractor

## task_state.py

**Class**: `TaskState`

**Storage layout** (per task):

```
{tasks_root}/{task_id}/
  ├── task.md          # Task description (evolves with refinement)
  ├── state.md         # Current state (replaced each run)
  ├── history.md       # Append-only run log
  ├── refine_log.md    # Append-only refinement turn log
  └── artifacts/       # Files produced during runs
```

**`tasks_root` default**: `~/.task-agents/tasks/`. Make it configurable
(accept a `root: Path` arg; plumb an env var override through the
package's config module if one exists).

**Required methods**:

```python
@dataclass
class TaskState:
    task_id: str
    root: Path

    # Construction
    @classmethod
    def create(cls, task_id, task_description, *, root, label=None) -> "TaskState": ...
    @classmethod
    def load(cls, task_id, *, root) -> "TaskState": ...
    def delete(self) -> None: ...

    # Paths (properties)
    task_dir, task_file, state_file, history_file, refine_log_file, artifacts_dir

    # Reading
    def render_for_agent(self, *, include_history: bool = False) -> str: ...

    # Writing
    def append_run_summary(self, *, summary, findings, open_questions, avoid_list) -> None: ...
    def append_refine_turn(self, *, user_message, agent_response) -> None: ...
    def update_task_description(self, new_description: str) -> None: ...
    def save_artifact(self, filename: str, content: str) -> Path: ...
```

### `create`

Initializes the task directory. Writes:

- `task.md` with `# Task: {id}` header, optional `**Type:** {label}`
  line, and `## Description\n\n{description}`.
- `state.md` with the "no runs yet" placeholder sections:
  `## Current status`, `## Key findings`, `## Open questions`,
  `## What NOT to try again` — each with `_None yet._` placeholder.
- `history.md` with just a header.
- `refine_log.md` with just a header.
- Empty `artifacts/` directory.

Idempotent — if the directory exists, overwrite (callers should
ensure unique IDs).

### `load`

Construct a `TaskState` pointing at an existing directory. Raise
`FileNotFoundError` if the directory doesn't exist.

### `render_for_agent`

Produces a markdown blob to inject into the system prompt. Format:

```
# Task context (memory)

You are working on an existing task. The following is what's known
so far. Build on this — don't start from scratch, and don't repeat
work that's already been done.

---

{contents of task.md}

---

{contents of state.md}

---

{contents of refine_log.md, if non-empty}

---

{contents of history.md, only if include_history=True}
```

Concretely: join with `\n\n---\n\n`. Skip refine_log if it has only
the header line (no actual turns recorded). History is excluded by
default because it's redundant with state.md and expensive in tokens.

### `append_run_summary`

Called by the pipeline's `finalize_execution` after a run completes
(and after any revision pass). Takes the four structured fields
produced by `extract_state`.

Behavior:

1. Append a new section to `history.md`:
   ```
   ## Run {ISO timestamp}

   {summary}
   ```
2. **Replace** `state.md` entirely with the current state. State is
   "what's true now," not "what happened." Format:
   ```markdown
   # State

   _Last updated: {timestamp}_

   ## Current status

   {summary}

   ## Key findings

   {findings or '_None yet._'}

   ## Open questions

   {open_questions or '_None yet._'}

   ## What NOT to try again

   {avoid_list or '_None yet._'}
   ```

### `append_refine_turn`

Append a timestamped entry to `refine_log.md`:

```
## Turn {ISO timestamp}

**User:** {user_message}

**Agent:** {agent_response}
```

### `update_task_description`

Replaces the description block in `task.md` while preserving the
header. Find the `## Description` marker, keep everything before it,
replace everything after it with the new description.

The refine_log preserves the history of how the task evolved, so the
"old" description isn't lost — it's just no longer active.

### `save_artifact`

Write `content` to `artifacts/{filename}`. Return the absolute path.
Caller is responsible for ensuring filenames are safe (no path
traversal).

## extract_state.py

**Function**: `extract_state`

**Purpose**: given a task's description and a run's output, return a
dict with the four structured fields (`summary`, `findings`,
`open_questions`, `avoid_list`) that `append_run_summary` takes.

Why a separate extractor instead of baking structured output into the
profile contract: profiles should stay focused on what the user sees.
Memory's schema can evolve (add fields, change prompts) without
touching every profile. The cost is one extra Haiku call per run;
it's worth it.

**Signature**:

```python
def extract_state(
    task_description: str,
    output: str,
    *,
    client: Anthropic | None = None,
) -> dict[str, str]:
```

Returns keys: `summary`, `findings`, `open_questions`, `avoid_list`.
All strings (possibly empty).

**Model**: `claude-haiku-4-5-20251001`

**Prompt** (inline in the Python file or as a sibling `.md` — both
fine; pick whichever matches the rest of the package's style):

```
You extract structured state fields from a completed task's output.
The fields feed a task's memory so future runs on the same task can
build on prior work.

Given the task description and the output, produce a JSON object:

- summary (1-3 sentences): what was accomplished this run
- findings (markdown bullets): concrete things learned, empty if none
- open_questions (markdown bullets): unresolved things, empty if none
- avoid_list (markdown bullets): dead ends to skip next time, empty
  if none

Be terse. Memory compresses the run; it doesn't duplicate it. If a
field has nothing concrete, return an empty string — don't invent.

Respond with a single JSON object, no preamble or fences.
```

**Safe default** (on parse failure): return `{"summary": output[:500]+"…", "findings": "", "open_questions": "", "avoid_list": ""}`.
A weak summary is fine; memory is append-only so it can be improved
on the next run.

## Testing

`memory/test_memory.py`:

- Use `tempfile.TemporaryDirectory` for the storage root.
- Test full lifecycle: create → load → append_run_summary → load
  → render_for_agent contains the summary → append_refine_turn →
  update_task_description.
- Verify `history.md` is append-only across multiple runs.
- Verify `state.md` is replaced (not appended) across runs.
- Don't mock the LLM extractor. Test it with a short real sample
  to verify the prompt shape works.

## Integration points

Pipeline calls `TaskState.create` in `prepare_task_for_execution`
when `task_id is None`. Calls `TaskState.load` when resuming.

Pipeline's `finalize_execution` calls `extract_state` and then
`state.append_run_summary`.

Pipeline's `handle_refine_turn` calls `state.append_refine_turn` and
optionally `state.update_task_description`.

The app's runner never touches memory directly. All memory access
goes through the pipeline.

## What NOT to build here

- **Cross-task search / indexing** — not in scope. Separate feature
  if/when needed.
- **Memory compaction or summarization** — memory is append-only
  and state.md is replaced each run, so size grows linearly only in
  history.md. That's fine for a long time. Add compaction later if
  token budgets become a problem.
- **Shared memory across tasks** — each task is isolated. Users
  don't want task A's state leaking into task B's context.
- **Versioning / undo** — `update_task_description` overwrites. If
  you want history, the refine_log preserves it. Don't build a
  separate versioning layer.
