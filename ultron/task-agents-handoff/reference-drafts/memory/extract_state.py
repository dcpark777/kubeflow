"""
Memory extractor.

After a run produces output, a small agent extracts the structured
state fields (summary, findings, open questions, avoid-list) that
task memory tracks.

Keeping this separate from the profile output contracts means:
- Profiles stay focused on what the USER sees
- Memory gets clean structured input without forcing every task to
  emit YAML-like trailers
- We can iterate on memory schema without rewriting all profiles

Usage:
    from extract_state import extract_state

    state_fields = extract_state(
        task_description=task,
        output=run_output,
    )
    state.append_run_summary(**state_fields)
"""
from __future__ import annotations

import json
from pathlib import Path

from anthropic import Anthropic

EXTRACTOR_MODEL = "claude-haiku-4-5-20251001"

EXTRACTOR_PROMPT = """You extract structured state fields from a
completed task's output. The fields feed a task's memory so future
runs on the same task can build on prior work.

Given the task description and the output, produce a JSON object with
these fields:

- **summary** (string, 1-3 sentences): what was accomplished in this
  run. Plain prose, user-facing. Not a rehash of the full output —
  the headline.
- **findings** (string, markdown bullets): concrete things learned
  or established during this run that should inform future runs.
  Empty string if nothing notable was discovered.
- **open_questions** (string, markdown bullets): things that came up
  during the run and remain unresolved. Empty string if there are
  none.
- **avoid_list** (string, markdown bullets): approaches tried and
  rejected, dead ends, or things that shouldn't be re-attempted on
  future runs. Empty string if there's nothing to warn future runs
  away from.

Be terse. Memory should compress the run, not duplicate it. If a
field has nothing concrete to say, return an empty string — don't
invent content.

Respond with a single JSON object, no preamble or markdown fences.
"""


def extract_state(
    task_description: str,
    output: str,
    *,
    client: Anthropic | None = None,
) -> dict[str, str]:
    """
    Extract structured state fields from a run's output.

    Returns a dict with keys: summary, findings, open_questions,
    avoid_list. All values are strings (possibly empty). On malformed
    output, returns a minimal dict with just the raw output as
    summary — memory is append-only so a weak summary is fine.
    """
    client = client or Anthropic()

    user_message = (
        f"# Task\n\n{task_description}\n\n"
        f"---\n\n"
        f"# Output\n\n{output}"
    )

    response = client.messages.create(
        model=EXTRACTOR_MODEL,
        max_tokens=800,
        system=EXTRACTOR_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()

    return _parse_extraction(raw, fallback_output=output)


def _parse_extraction(raw: str, fallback_output: str) -> dict[str, str]:
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "summary": _truncate(fallback_output, 500),
            "findings": "",
            "open_questions": "",
            "avoid_list": "",
        }

    return {
        "summary": _as_str(parsed.get("summary"))
        or _truncate(fallback_output, 500),
        "findings": _as_str(parsed.get("findings")),
        "open_questions": _as_str(parsed.get("open_questions")),
        "avoid_list": _as_str(parsed.get("avoid_list")),
    }


def _as_str(val: object) -> str:
    return val if isinstance(val, str) else ""


def _truncate(text: str, max_chars: int) -> str:
    return text if len(text) <= max_chars else text[: max_chars - 20] + "…"
