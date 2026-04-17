"""
Critique pass.

After execution, a reviewer agent reads the task description and the
produced output, and returns either 'pass' or 'revise' with specific
guidance. The dispatcher then decides whether to accept the output or
run a revision pass.

Usage:
    from critique import critique_output, should_critique

    if should_critique(selection_tier="opus", label="planning"):
        critique = critique_output(task_description, output)
        if critique.verdict == "revise":
            revised = run_revision(original_output, critique.revision_guidance)
            # Ship revised, not original

This module provides the critique call. The revision pass itself is a
normal execution call with the revision_guidance injected — your
dispatcher handles that.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from anthropic import Anthropic

Verdict = Literal["pass", "revise"]
Severity = Literal["major", "minor"]

# Critique should use a capable model — shallow critique is worse than
# no critique, because it creates false confidence. Sonnet is the right
# tier for this: it'll catch real issues without the cost of Opus.
CRITIQUE_MODEL = "claude-sonnet-4-6"
PROMPT_PATH = Path(__file__).parent / "critique-prompt.md"


@dataclass(frozen=True)
class Issue:
    severity: Severity
    description: str


@dataclass(frozen=True)
class CritiqueResult:
    verdict: Verdict
    issues: tuple[Issue, ...]
    revision_guidance: str


def should_critique(
    *,
    selection_tier: str,
    label: str,
    explicit_high_stakes: bool = False,
) -> bool:
    """
    Decide whether to run critique on this task.

    The rule: critique when the stakes are high enough to justify the
    extra latency and cost. Defaults:

    - Opus-tier tasks — these were already judged high-stakes by the
      selector, critique is cheap insurance
    - Anything the caller explicitly flags as high-stakes
    - Planning tasks at Sonnet tier — plans are decisions users act on
    - Research tasks at Sonnet tier — users cite these to make
      decisions

    Skipped by default:
    - Haiku-tier tasks — low stakes by construction
    - Brainstorming — variance is the goal, "quality" is subjective
    - Coding at Sonnet — the diff itself is the verification
    """
    if explicit_high_stakes:
        return True
    if selection_tier == "opus":
        return True
    if selection_tier == "sonnet" and label in ("planning", "research"):
        return True
    return False


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def critique_output(
    task_description: str,
    output: str,
    *,
    client: Anthropic | None = None,
) -> CritiqueResult:
    """
    Run the critique pass.

    On malformed critic output, returns a pass verdict — false
    positives (spurious revisions) are more annoying than false
    negatives (missed issues).
    """
    client = client or Anthropic()

    user_message = (
        f"# Task\n\n{task_description}\n\n"
        f"---\n\n"
        f"# Output to review\n\n{output}"
    )

    response = client.messages.create(
        model=CRITIQUE_MODEL,
        max_tokens=1500,
        system=_load_system_prompt(),
        messages=[{"role": "user", "content": user_message}],
    )

    raw = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()

    return _parse_critique(raw)


def _parse_critique(raw: str) -> CritiqueResult:
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    # Safe default: pass. Shipping unreviewed output is better than
    # spuriously blocking the user.
    safe_pass = CritiqueResult(
        verdict="pass", issues=(), revision_guidance=""
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return safe_pass

    verdict = parsed.get("verdict")
    if verdict not in ("pass", "revise"):
        return safe_pass

    raw_issues = parsed.get("issues", [])
    issues: list[Issue] = []
    if isinstance(raw_issues, list):
        for item in raw_issues:
            if not isinstance(item, dict):
                continue
            severity = item.get("severity")
            description = item.get("description", "")
            if severity in ("major", "minor") and description:
                issues.append(
                    Issue(severity=severity, description=description)
                )

    guidance = parsed.get("revision_guidance", "")
    if not isinstance(guidance, str):
        guidance = ""

    return CritiqueResult(
        verdict=verdict,
        issues=tuple(issues),
        revision_guidance=guidance,
    )


def build_revision_prompt(
    original_output: str,
    guidance: str,
) -> str:
    """
    Build the user message for a revision pass.

    The revision is a normal execution call to the same profile, but
    with this message instead of the original task. The agent sees
    what it produced, what needs to change, and revises.
    """
    return (
        "You produced the following output for this task:\n\n"
        "---\n\n"
        f"{original_output}\n\n"
        "---\n\n"
        "A reviewer flagged the following issues to address:\n\n"
        f"{guidance}\n\n"
        "Revise the output to address these specifically. Keep what's "
        "working; change what's flagged. Don't rewrite from scratch."
    )
