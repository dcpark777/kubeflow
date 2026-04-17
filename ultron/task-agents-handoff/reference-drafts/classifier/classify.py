"""
Task classifier.

Routes incoming tasks to one of: planning, brainstorming, coding,
research, or unclear. Uses a small fast model and a cached system
prompt.

Usage:
    from classify import classify_task

    result = classify_task("Migrate our batch pipelines to Jenkins")
    # ClassificationResult(label="planning", uncertain=False, candidates=None)

    if result.uncertain:
        # Ask user to pick between result.candidates
        ...
    else:
        # Auto-route to profiles/{label}-execute.md
        ...
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from anthropic import Anthropic

Label = Literal["planning", "brainstorming", "coding", "research", "unclear"]

VALID_LABELS: set[str] = {
    "planning",
    "brainstorming",
    "coding",
    "research",
    "unclear",
}

# Small, fast model for classification. A bigger model is overkill here —
# the task is bounded and the prompt carries most of the reasoning.
CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"

# The classifier prompt lives alongside this file so it's version-controlled
# with the code and easy to iterate on without editing Python.
PROMPT_PATH = Path(__file__).parent / "classifier-prompt.md"


@dataclass(frozen=True)
class ClassificationResult:
    label: Label
    uncertain: bool
    # Populated only when label == "unclear". The two most likely
    # alternatives, for surfacing to the user.
    candidates: tuple[str, ...] | None = None


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def classify_task(
    task_description: str,
    *,
    client: Anthropic | None = None,
) -> ClassificationResult:
    """
    Classify a task description into one of the known labels.

    Returns ClassificationResult. If the model returns malformed output
    or a label we don't recognize, falls back to uncertain with no
    candidates — the app should then route to manual selection.
    """
    client = client or Anthropic()

    response = client.messages.create(
        model=CLASSIFIER_MODEL,
        max_tokens=100,
        system=_load_system_prompt(),
        messages=[{"role": "user", "content": task_description}],
    )

    # Response should be a single text block with a JSON object.
    raw = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()

    return _parse_classifier_output(raw)


def _parse_classifier_output(raw: str) -> ClassificationResult:
    """
    Parse the JSON the classifier returns. Forgiving by design —
    classification is cheap to retry but expensive to get wrong, so
    we bias toward 'uncertain' on any parsing trouble.
    """
    # Strip accidental code fences if the model adds them despite the prompt.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ClassificationResult(label="unclear", uncertain=True)

    label = parsed.get("label")
    if label not in VALID_LABELS:
        return ClassificationResult(label="unclear", uncertain=True)

    if label == "unclear":
        candidates = parsed.get("candidates")
        if isinstance(candidates, list) and all(
            c in VALID_LABELS and c != "unclear" for c in candidates
        ):
            return ClassificationResult(
                label="unclear",
                uncertain=True,
                candidates=tuple(candidates),
            )
        return ClassificationResult(label="unclear", uncertain=True)

    return ClassificationResult(label=label, uncertain=False)


# ---------------------------------------------------------------------------
# Profile resolution
# ---------------------------------------------------------------------------

PROFILES_DIR = Path(__file__).parent.parent / "profiles"


def resolve_profile(label: Label, mode: Literal["execute", "refine"]) -> Path:
    """
    Map a classification label + mode to the profile file to load.

    Raises if the label is 'unclear' — the app must resolve that upstream
    by asking the user before calling this.
    """
    if label == "unclear":
        raise ValueError(
            "Cannot resolve profile for 'unclear' label. Ask the user to "
            "pick between candidates first."
        )
    return PROFILES_DIR / f"{label}-{mode}.md"
