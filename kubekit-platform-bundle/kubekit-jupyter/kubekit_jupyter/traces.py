"""Silent trace capture for components executed in notebooks.

When a data scientist runs a cell with %%kfp_component, the magic records
the types and shapes of the arguments the component was called with and the
type/shape of its return value. These traces are stored in a local cache and
consumed later by `kubekit decompile` to scaffold regression tests.

No AI here. Just structured capture and recall.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Trace:
    component_name: str
    args_repr: dict[str, str]   # arg name -> short repr of value
    return_repr: str | None     # short repr of return value
    notes: list[str] = field(default_factory=list)


class TraceStore:
    """In-memory trace store keyed by component name.

    v1 is process-local. A real implementation would persist to ~/.kubekit/traces/
    keyed by notebook path so traces survive across kernel restarts.
    """
    def __init__(self) -> None:
        self._traces: dict[str, list[Trace]] = {}

    def record(self, trace: Trace) -> None:
        self._traces.setdefault(trace.component_name, []).append(trace)

    def for_component(self, name: str) -> list[Trace]:
        return list(self._traces.get(name, []))

    def all(self) -> dict[str, list[Trace]]:
        return dict(self._traces)


_STORE = TraceStore()


def get_store() -> TraceStore:
    return _STORE


def short_repr(value: Any, max_len: int = 80) -> str:
    """A stable, short representation of a value for trace storage."""
    try:
        r = repr(value)
    except Exception:
        r = f"<{type(value).__name__}>"
    if len(r) > max_len:
        r = r[:max_len - 3] + "..."
    return r
