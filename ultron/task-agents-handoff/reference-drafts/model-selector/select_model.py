"""
Model selector.

Given a task description, its classification label, and whether we're
in execute or refine mode, returns the Claude tier and thinking mode
to use.

Usage:
    from select_model import select_model

    result = select_model(
        task_description="Migrate our batch pipelines to Jenkins",
        label="planning",
        mode="execute",
    )
    # SelectionResult(tier="opus", thinking="adaptive", reason="...")

    cmd_args = result.to_claude_code_args()
    # ["--model", "opus", "--effort", "auto"]
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from anthropic import Anthropic

Tier = Literal["haiku", "sonnet", "opus"]
Thinking = Literal["off", "adaptive", "high"]
Mode = Literal["execute", "refine"]
Label = Literal["planning", "brainstorming", "coding", "research"]

VALID_TIERS: set[str] = {"haiku", "sonnet", "opus"}
VALID_THINKING: set[str] = {"off", "adaptive", "high"}

# The selector itself runs on a small model — it's a routing decision,
# not reasoning work. Haiku is plenty.
SELECTOR_MODEL = "claude-haiku-4-5-20251001"

PROMPT_PATH = Path(__file__).parent / "selector-prompt.md"


@dataclass(frozen=True)
class SelectionResult:
    tier: Tier
    thinking: Thinking
    reason: str

    def to_claude_code_args(self) -> list[str]:
        """
        Translate to Claude Code CLI flags.

        Claude Code's --model flag accepts tier aliases (haiku/sonnet/opus).
        Its --effort flag controls thinking: "auto" = adaptive, "off" =
        disabled, "high" = maximum. Check your Claude Code version's docs
        and adjust mappings if they've changed.
        """
        args = ["--model", self.tier]

        effort_map = {
            "off": "off",
            "adaptive": "auto",
            "high": "high",
        }
        args.extend(["--effort", effort_map[self.thinking]])
        return args

    def to_api_params(self) -> dict:
        """
        Translate to Anthropic API params, for apps calling the API
        directly instead of Claude Code.

        Returns a dict with 'model' and optionally 'thinking'. Caller
        merges this into their messages.create() kwargs.
        """
        model_map = {
            # Pinned dated IDs for reproducibility; bump when new
            # point releases land and you've verified them.
            "haiku": "claude-haiku-4-5-20251001",
            "sonnet": "claude-sonnet-4-6",
            "opus": "claude-opus-4-7",
        }
        params: dict = {"model": model_map[self.tier]}

        if self.thinking == "off":
            # Explicitly disable thinking. For models with adaptive
            # thinking as the default (Opus 4.6+, Sonnet 4.6), this
            # requires setting thinking to a disabled state; check
            # current API docs for the exact shape.
            pass  # No-op: caller's default is typically thinking-off
        elif self.thinking == "high":
            params["thinking"] = {
                "type": "enabled",
                "budget_tokens": 16000,
            }
        # adaptive: omit the param; the model handles it on 4.6+

        return params


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def select_model(
    task_description: str,
    label: Label,
    mode: Mode,
    *,
    client: Anthropic | None = None,
) -> SelectionResult:
    """
    Choose a tier + thinking mode for the given task.

    Falls back to a safe default (sonnet/adaptive) if the selector
    returns malformed output — selection is never supposed to fail
    the request.
    """
    client = client or Anthropic()

    user_message = (
        f"Task: {task_description}\n"
        f"Label: {label}\n"
        f"Mode: {mode}"
    )

    response = client.messages.create(
        model=SELECTOR_MODEL,
        max_tokens=150,
        system=_load_system_prompt(),
        messages=[{"role": "user", "content": user_message}],
    )

    raw = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()

    return _parse_selector_output(raw)


def _parse_selector_output(raw: str) -> SelectionResult:
    """
    Parse the selector's JSON output. On any malformed response,
    return a safe sonnet/adaptive default — selection failures
    shouldn't break task routing.
    """
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    safe_default = SelectionResult(
        tier="sonnet",
        thinking="adaptive",
        reason="selector fallback (malformed output)",
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return safe_default

    tier = parsed.get("tier")
    thinking = parsed.get("thinking")
    reason = parsed.get("reason", "")

    if tier not in VALID_TIERS or thinking not in VALID_THINKING:
        return safe_default

    return SelectionResult(
        tier=tier,
        thinking=thinking,
        reason=reason if isinstance(reason, str) else "",
    )
