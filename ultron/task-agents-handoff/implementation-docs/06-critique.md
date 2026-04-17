# 06 — Critique

Post-execution quality gate. Reads the task description + the
produced output, and returns either `pass` (ship it) or `revise`
(run one revision pass with this guidance).

**Single-pass revision only.** Don't build a loop. Two-pass critique
(generate → revise) improves quality. Three-plus passes mostly waste
tokens. The cost/quality curve flattens fast.

## Files

`task_agents/critique/critique.py`
`task_agents/critique/critique-prompt.md`

## Gate function

Not every task gets critiqued. The gate:

```python
def should_critique(
    *,
    selection_tier: str,
    label: str,
    explicit_high_stakes: bool = False,
) -> bool:
    if explicit_high_stakes:
        return True
    if selection_tier == "opus":
        return True
    if selection_tier == "sonnet" and label in ("planning", "research"):
        return True
    return False
```

Rationale:

- **Opus-tier** tasks were already judged high-stakes by the selector.
  The critique cost is small relative to the execution cost, and the
  user is already waiting longer for Opus-grade reasoning.
- **Sonnet planning and research** are decisions users act on. Plans
  and research writeups get shipped, shared, and cited. Worth the
  extra check.
- **Haiku tasks** are low-stakes by construction (selector picks
  Haiku when it judges the task simple). Critique here usually finds
  noise.
- **Sonnet coding** is skipped because the diff itself is the
  verification — tests run, code compiles, reviewer examines the
  change. Critique on coding outputs tends to nitpick stylistic
  choices rather than catch real bugs.
- **Brainstorming** is skipped because "quality" is subjective —
  the critic will suppress exactly the weird, variant ideas that make
  brainstorming valuable.

If the app wants to force critique on a specific task, pass
`explicit_high_stakes=True`. Useful for user-flagged "this is
important" tasks.

## Critique function

**Signature**:

```python
def critique_output(
    task_description: str,
    output: str,
    *,
    client: Anthropic | None = None,
) -> CritiqueResult:
```

**Model**: `claude-sonnet-4-6`. Shallow critique is worse than no
critique — it creates false confidence. Haiku isn't strong enough at
reading outputs against task descriptions for this to work. Sonnet
is the right tier; Opus is overkill because the critique itself is
bounded.

**Message to Claude**:

```
# Task

{task_description}

---

# Output to review

{output}
```

## Critique prompt

Key sections to include in `critique-prompt.md`:

### What to check

The things a careful colleague would catch on a second read:

1. Missed requirements — tasks with multiple asks often get partial
   responses
2. Wrong kind of answer — plan requested but prose produced;
   comparison asked for but single recommendation given
3. Hallucinated specifics — fake version numbers, invented APIs,
   unsourced statistics
4. Un-actionable steps — plan milestones that are restatements of
   the goal rather than concrete work
5. Contradictions — output contradicts itself or the task
6. Critical omissions — reasonable expectations the output misses
   (e.g., migration plan with no rollback)

### What NOT to critique

Important — the critic will overreach if you don't bound it:

- Style / tone, unless the task asked for a specific style
- Length, unless dramatically off
- "I'd approach this differently" preferences
- Minor phrasing
- Scope creep (things the task didn't ask for)

### The bar

Only flag issues that, if pointed out, the user would agree with. If
the output is solid, pass it. `pass` is a valid and common verdict.

Over-critiquing is worse than under-critiquing: every spurious
revision burns the user's time and tokens.

### Severity rules

- `major` — output fails to deliver on the task in a way the user
  will notice. Requires revision.
- `minor` — real issue but output is still usable.

Verdict rule: `pass` if zero majors AND at most one minor.
`revise` otherwise.

### Output format

```json
{
  "verdict": "pass" | "revise",
  "issues": [
    {"severity": "major" | "minor", "description": "..."}
  ],
  "revision_guidance": "..."
}
```

`revision_guidance` is a brief paragraph telling the next agent what
to change. Empty string when verdict is pass.

### Examples

Include 2-3 worked examples in the prompt showing:
- A pass case (output is fine, no issues)
- A clear revise case (missed requirement + un-actionable steps)
- An edge case (one minor issue → still pass)

## Revision prompt builder

**Function**:

```python
def build_revision_prompt(original_output: str, guidance: str) -> str:
```

Returns a user message to send on the revision pass:

```
You produced the following output for this task:

---

{original_output}

---

A reviewer flagged the following issues to address:

{guidance}

Revise the output to address these specifically. Keep what's working;
change what's flagged. Don't rewrite from scratch.
```

The revision runs on the **same profile and model** as the original
execution — this isn't a second routing decision, it's the same agent
in the same mode doing one more pass with targeted feedback.

The pipeline handles the revision dispatch by calling the app's
`run_executor` callback with this prompt.

## Safe defaults

On any malformed critic output: return `CritiqueResult(verdict="pass", issues=(), revision_guidance="")`.

This is asymmetric on purpose: spurious revisions are more annoying
to users than missed issues. If the critic fails, ship the original.

On any revision call failure: let it propagate. The app should handle
display of revision errors.

## Testing

`test_critique.py`:

- Curated set of (task, output, expected_verdict) tuples.
- Include: clearly-good outputs (should pass), clearly-bad outputs
  (should revise), edge cases.
- Accept some margin — "did it catch the right kind of issue" matters
  more than "did it produce exactly the string I expected."
- Track the pass/revise ratio over a larger sample (30+ cases). Target
  ~20% revise rate on tasks that reach the critique gate. Much higher
  means noisy critic; much lower means it's not earning its cost.

## Where this plugs in

Pipeline `finalize_execution`:

```python
def finalize_execution(*, task_id, task_description, output,
                      should_run_critique, run_executor):
    final_output = output
    was_revised = False
    critique_result = None

    if should_run_critique and run_executor is not None:
        critique_result = critique_output(task_description, output)
        if critique_result.verdict == "revise":
            revision_prompt = build_revision_prompt(
                output, critique_result.revision_guidance
            )
            final_output = run_executor(revision_prompt)
            was_revised = True

    # ... then memory update on final_output
```

Note: if `run_executor` is None (e.g., in tests), critique still runs
but revision can't happen. Return the critique_result to the caller
anyway — the app may want to surface flagged issues to the user even
if revision wasn't dispatched.
