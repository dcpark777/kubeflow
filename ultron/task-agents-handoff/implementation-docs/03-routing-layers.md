# 03 — Routing layers

Three modules, same shape. Build all three before the pipeline.

Each routing layer consists of:

1. A markdown **prompt file** (system prompt sent to Claude)
2. A Python **module** that:
   - Loads the prompt from disk at call-time (not import-time; makes
     iteration cheap)
   - Calls Claude Haiku with the task description
   - Parses the JSON response into a frozen dataclass
   - Falls back to a safe default on malformed output

None of these call each other. They're independent and testable.

## Shared conventions

All three use:

- Model: `claude-haiku-4-5-20251001`
- `max_tokens`: small (100-1500 depending on output size)
- Response format: JSON object only, no markdown fences, no preamble
- Parser: strip accidental code fences first, then `json.loads`, then
  validate field types and fall back on any mismatch

All three accept an optional `client: Anthropic | None = None`
parameter. Default to constructing `Anthropic()` if None.

All three load their prompt from a sibling `.md` file:

```python
PROMPT_PATH = Path(__file__).parent / "classifier-prompt.md"  # etc.

def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")
```

## Classifier

**File**: `task_agents/classifier/classify.py`
**Prompt**: `task_agents/classifier/classifier-prompt.md`

**Function signature**:

```python
def classify_task(
    task_description: str,
    *,
    client: Anthropic | None = None,
) -> ClassificationResult:
```

**Labels it chooses from**: `planning`, `brainstorming`, `coding`,
`research`, `unclear`. When `unclear`, it returns candidate labels
(the two most likely real labels) so the app can present a narrow
choice to the user instead of the full 4-way picker.

**Prompt guidance** (summary for the markdown):

- The label is determined by what the *output* looks like, not what
  vocabulary the user uses. "Plan a refactor" that's really coding
  is `coding`, not `planning`. "Research what to build" that's
  really brainstorming is `brainstorming`, not `research`.
- Return `unclear` when genuinely torn — false confidence is worse
  than asking.
- Output is a single JSON object: `{"label": "..."}` or
  `{"label": "unclear", "candidates": ["planning", "research"]}`.

**Safe default**: `ClassificationResult(label="unclear", uncertain=True)`.

**Tests** (`test_classifier.py`): run ~12 realistic tasks covering
easy cases, traps where surface vocabulary misleads, and cases that
should be unclear. Mark trap cases as `unclear_ok=True` so "unclear"
counts as a pass there.

## Decomposer

**File**: `task_agents/decomposer/decompose.py`
**Prompt**: `task_agents/decomposer/decomposer-prompt.md`

**Function signature**:

```python
def decompose_task(
    task_description: str,
    *,
    client: Anthropic | None = None,
) -> DecomposeResult:  # SingleResult | CompoundResult | UnclearDecomposition
```

**Decision criteria** (summary for the markdown):

- Compound when the task contains 2+ independent sub-tasks with
  different output shapes that would benefit from being handled
  separately.
- NOT compound when the task is one coherent goal with multiple
  milestones (that's `planning`) or one task with multiple files
  (that's `coding`).
- Test: if you removed one sub-part, would the remainder still be
  a meaningful task the user would want? If yes → compound. If the
  remainder feels incomplete or pointless → single.
- Bias toward single. Over-splitting is a worse failure mode than
  under-splitting.

**Output schema**:

```json
{"type": "single"}

{
  "type": "compound",
  "subtasks": [
    {"name": "...", "description": "...", "depends_on": []},
    {"name": "...", "description": "...", "depends_on": [0]}
  ]
}

{"type": "unclear", "reason": "..."}
```

Sub-task `description` fields must be **standalone** — they should
include any context from the parent task that the sub-task needs,
because each sub-task goes through its own pipeline and won't have
access to the others except via explicitly-wired dependencies.

**Safe default**: `SingleResult()`. Treating a failure as single is
better than asking the user or failing loudly.

**Validation on parse**:

- If type is `compound` but sub-tasks list has fewer than 2 valid
  items (each needs `name` and `description`), treat as `SingleResult()`.
- `depends_on` values must be ints; otherwise empty.

**Tests**: eval harness similar to classifier, but for decomposition.
Include clear-single, clear-compound, and borderline cases.

## Selector

**File**: `task_agents/selector/select_model.py`
**Prompt**: `task_agents/selector/selector-prompt.md`

**Function signature**:

```python
def select_model(
    task_description: str,
    label: Label,
    mode: Mode,
    *,
    client: Anthropic | None = None,
) -> SelectionResult:
```

**Message to the model**:

```
Task: {task_description}
Label: {label}
Mode: {mode}
```

**Decision criteria** (summary for the markdown):

Two axes: how hard is the reasoning, and how much does getting it
right matter. Map to:

- Trivial + low stakes → `haiku`
- Moderate + normal stakes → `sonnet`
- Hard reasoning OR high stakes → `opus`
- When torn → pick cheaper unless signals push otherwise

Thinking default by tier:

- `haiku` → `off`
- `sonnet` → `adaptive`
- `opus` → `adaptive` (force `high` only for genuinely hard reasoning)

Mode overrides: refine mode caps at `sonnet`. Refinement is
question-asking, not heavy lifting.

Label priors: sonnet is the default. Opus for multi-quarter planning,
gnarly debugging, multi-dimensional research synthesis. Haiku for
trivial coding, short brainstorms in familiar domains.

**Output schema**:

```json
{"tier": "sonnet", "thinking": "adaptive", "reason": "short phrase"}
```

The `reason` is <15 words and used for logging.

**Safe default**: `SelectionResult(tier="sonnet", thinking="adaptive", reason="selector fallback")`.

**Translation methods on SelectionResult**:

```python
def to_claude_code_args(self) -> list[str]:
    """Returns ["--model", tier, "--effort", effort_for_thinking]."""
    effort_map = {"off": "off", "adaptive": "auto", "high": "high"}
    return ["--model", self.tier, "--effort", effort_map[self.thinking]]

def to_api_params(self) -> dict:
    """Returns {'model': dated_id, optionally 'thinking': {...}}."""
    model_map = {
        "haiku": "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-4-6",
        "opus": "claude-opus-4-7",
    }
    params = {"model": model_map[self.tier]}
    if self.thinking == "high":
        params["thinking"] = {"type": "enabled", "budget_tokens": 16000}
    # "off" and "adaptive" don't need explicit params on 4.6+ models
    return params
```

**Tests**: use "acceptable band" testing rather than exact-match.
Each test case has a set of tiers that would be reasonable; test
passes if the selector lands in the set. Planning tasks at the top
of the complexity range should be `opus`; trivial coding should be
`haiku`; most real tasks are an acceptable-band of `{sonnet}` or
`{sonnet, opus}`.

## Prompt authoring notes

For all three prompts:

- Write in imperative voice. "Return one of these labels" not "The
  labels you can return are".
- Include 4-6 concrete examples with labeled input and expected
  output JSON. Examples carry more weight than abstract rules.
- Include a "when NOT to" section. Overtriggering is a real failure
  mode (classifier returning unclear too often, decomposer splitting
  too eagerly, selector picking opus too much).
- Keep the prompt under ~300 lines. Long prompts are expensive and
  get ignored past the middle.

Prior drafts for each prompt exist in the reference package this plan
is derived from — check them for the shape of good examples.
