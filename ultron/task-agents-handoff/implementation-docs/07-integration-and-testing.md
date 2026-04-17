# 07 — Integration and testing

Wire `task_agents/` into the existing app, then verify end-to-end.

## Runner integration

The existing app has a dispatcher that spawns Claude Code for a task.
Modify it to use the pipeline.

### Before (sketch)

```python
def run_task(user_task: str) -> str:
    # Generic system prompt, generic model
    return launch_claude_code(
        prompt=SYSTEM_PROMPT + "\n\nTask: " + user_task,
        model="sonnet",
    )
```

### After (sketch)

```python
from task_agents import handle_new_task_submission, finalize_execution
from task_agents.memory.task_state import TaskState

def run_task(user_task: str) -> Response:
    payload = handle_new_task_submission(user_task)

    if payload["action"] == "ask_user_label":
        return Response(kind="prompt", candidates=payload["candidates"])

    if payload["action"] == "ask_user_decomposition":
        return Response(kind="prompt_split", ...)

    if payload["action"] == "execute_compound":
        return run_compound(payload)

    # Single task execute
    return run_single_execute(payload)


def run_single_execute(payload) -> Response:
    # Compose the system prompt
    profile_content = Path(payload["profile_path"]).read_text()
    system_prompt = (
        BASE_SYSTEM_PROMPT
        + "\n\n"
        + profile_content
        + ("\n\n" + payload["memory_context"] if payload["memory_context"] else "")
        + ("\n\n" + payload["dependency_context"] if payload["dependency_context"] else "")
    )

    # Launch Claude Code with the selector's args
    output = launch_claude_code(
        prompt=system_prompt,
        cli_args=payload["claude_code_args"],
        task_description=user_task,
    )

    # Let the pipeline decide whether to critique + revise
    def rerun_with_revision(revision_message: str) -> str:
        return launch_claude_code(
            prompt=system_prompt,
            cli_args=payload["claude_code_args"],
            user_message=revision_message,
        )

    final = finalize_execution(
        task_id=payload["task_id"],
        task_description=user_task,
        output=output,
        should_run_critique=payload["should_run_critique"],
        run_executor=rerun_with_revision,
    )

    return Response(kind="done", output=final.output, was_revised=final.was_revised)
```

The key integration points:

1. **Call `handle_new_task_submission` first.** Don't launch Claude
   Code until you have a dispatch payload.
2. **Handle the three `ask_user_*` actions** by bubbling up to the
   UI. These are normal control flow, not errors.
3. **Build the system prompt from the payload fields.** Base prompt +
   profile content + memory context + dependency context, joined
   with blank lines.
4. **Pass a `run_executor` callback to `finalize_execution`.** This is
   how the pipeline triggers revision without owning the execution
   machinery.

## Compound task handling

Compound tasks require the app's runner to sequence sub-tasks
respecting dependencies. Rough shape:

```python
def run_compound(payload) -> Response:
    parent_id = payload["parent_task_id"]
    subtask_plans = payload["subtask_plans"]
    outputs: dict[int, tuple[str, str]] = {}  # idx -> (name, output)

    for idx, plan in enumerate(subtask_plans):
        # Wait for deps to be ready (here: synchronous, in order)
        dep_outputs = {
            subtask_plans[d]["name"]: outputs[d][1]
            for d in plan["depends_on_indices"]
        }

        # Run this sub-task through the single-task path
        sub_payload = prepare_task_for_execution(
            task_description=plan["description"],
            task_id=plan["subtask_id"],
            parent_task_id=parent_id,
            dependency_outputs=dep_outputs,
        )
        if sub_payload["action"] != "execute":
            # Unlikely but possible — sub-task classified as unclear
            # Handle by falling back (or asking user; runtime choice)
            ...

        output = run_single_execute(sub_payload).output
        outputs[idx] = (plan["name"], output)

    return Response(
        kind="compound_done",
        subtask_outputs=[(name, out) for name, out in outputs.values()],
    )
```

Optional: run sub-tasks with no remaining dependencies in parallel.
Not required for v1. Serialize first, parallelize later if latency
matters.

## Refinement integration

Refine mode is chat-driven — the existing chat UI handles turns. The
pipeline hooks in via `handle_refine_turn`:

```python
def on_refine_turn(task_id, user_message):
    payload = prepare_task_for_execution(
        task_description=load_task_description(task_id),
        task_id=task_id,
        mode="refine",
    )
    # Handle payload the same way as execute — it returns an ExecutePayload
    # with the refine profile and (typically) sonnet tier

    agent_response = launch_claude_code(
        prompt=build_prompt_from_payload(payload),
        cli_args=payload["claude_code_args"],
        user_message=user_message,
    )

    # Extract the new task description if the refine profile produced one
    # (look for a "## Proposed task description" block in agent_response)
    new_desc = extract_proposed_description(agent_response)

    handle_refine_turn(
        task_id=task_id,
        user_message=user_message,
        agent_response=agent_response,
        new_task_description=new_desc,
    )

    return agent_response
```

The refine profile's output contract includes a "proposed task
description" block in each turn. Parse that block and pass it as
`new_task_description` so `task.md` stays current.

## Testing

### Unit-ish tests (per module)

Each routing layer has a test file described in doc 03. Memory has
one in doc 05. Critique has one in doc 06.

These all hit real LLMs. Don't mock the client — the whole point is
to verify the prompts produce sensible outputs. Accept some flakiness
at the margins; use "acceptable band" assertions where appropriate.

Budget: running the full suite should cost well under $1 and complete
in under a minute.

### End-to-end tests

Ship at least these in `task_agents/test_e2e.py`:

**Test 1: single simple task, no memory, no critique.**
```
task = "Rename foo to bar in config.py"
# Expect: classify=coding, select=haiku/off, no critique
```

**Test 2: single complex task, opus, critique runs.**
```
task = "Migrate our batch pipelines from Airflow to Jenkins across Q2-Q3"
# Expect: classify=planning, select=opus, critique runs
```

**Test 3: compound task.**
```
task = "Research vector DBs, pick one, write a migration plan"
# Expect: decompose=compound with 2 subtasks, deps=[0] on subtask 1
```

**Test 4: unclear classification.**
```
task = "Help me with the auth system"
# Expect: classify=unclear, payload action = ask_user_label
```

**Test 5: memory persists across runs.**
```
# 1. Create task, run it, finalize_execution writes state
# 2. Load TaskState, verify state.md has content from the run
# 3. Run again (same task_id), verify memory_context in payload is non-empty
```

**Test 6: critique triggers revision.**
```
# Use a mock run_executor that returns a deliberately-bad output the first
# call, and a good output the second. Verify finalize_execution calls the
# executor twice and returns was_revised=True.
```

Test 6 is the one test where mocking makes sense — you want
deterministic critique-then-revise flow.

### Stress tests (run before trusting broadly)

After the test suite passes, run these against 20-30 real tasks from
the app's task history:

1. **Decomposer false-positive rate.** How often does it split tasks
   that should be single? Target: <10%. If higher, tighten the "what
   is NOT compound" section of the prompt.

2. **Critique noise rate.** On the subset that reaches the critique
   gate, what fraction gets flagged `revise`? Target: ~20%. Much
   higher means the critic is noisy (tighten "what NOT to critique");
   much lower means it's not catching real issues (loosen).

3. **Memory helpfulness.** Pick 5 tasks that got iterated on (run
   multiple times). Compare outputs with memory enabled vs. disabled.
   Memory should help — if it distracts, simplify what
   `render_for_agent` emits.

4. **Selector calibration.** For 30 tasks, note the tier picked and
   judge afterward whether it was right, too-big, or too-small.
   Target: >80% "right", with the errors roughly balanced between
   too-big and too-small. Systematically too-big means cost pressure
   on the prompt; systematically too-small means quality pressure.

Log the results somewhere persistent. You'll want to re-run these
checks after every prompt change.

### Observability

Emit a structured log line per task with:

```json
{
  "task_id": "...",
  "parent_task_id": null,
  "description_hash": "sha256...",
  "decomposer_result": "single",
  "label": "planning",
  "tier": "opus",
  "thinking": "adaptive",
  "selection_reason": "multi-quarter migration",
  "critique_verdict": "revise",
  "was_revised": true,
  "total_latency_ms": 45302,
  "routing_latency_ms": 1850
}
```

This is what you look at when the pipeline is behaving oddly. Keep
it structured; your existing observability stack can pick it up.

## Deployment

### Skills

The skills in `task_agents/skills/` need to be reachable by Claude
Code at runtime. Options (see doc 04):

- Copy to `~/.claude/skills/` on the server (user-scope, simplest)
- Copy to a per-task `.claude/skills/` directory (project-scope,
  cleaner but requires per-task setup)

For v1, user-scope on the server where Claude Code runs is fine.
Document the copy step in the deploy runbook.

### Memory root

Default `~/.task-agents/tasks/` is fine for a single-server app. For
multi-server or containerized deployments, plumb a config option so
it can point at a shared volume. Memory must persist across
deployments or tasks lose their state.

### Model bumps

When a new Claude model ships, update:

- `SELECTOR_MODEL`, `CLASSIFIER_MODEL`, `DECOMPOSER_MODEL`,
  `EXTRACTOR_MODEL` — likely stay on whatever current Haiku is
- `CRITIQUE_MODEL` — likely stay on current Sonnet
- The `model_map` in `SelectionResult.to_api_params()` — update to
  newest dated IDs after verifying

Run the full stress test suite after any model bump before rolling to
production.

## Done criteria

The integration is done when:

1. All tests in `test_e2e.py` pass.
2. The stress tests on 20-30 real tasks pass the targets above.
3. The existing app's task-creation flow uses the pipeline end-to-end.
4. Refinement chat is wired through `handle_refine_turn` and updates
   `task.md` correctly when proposed descriptions are accepted.
5. Structured logs are emitted per task and visible in the app's
   observability.

At that point, the layered pipeline is live and every task the app
runs benefits from it.
