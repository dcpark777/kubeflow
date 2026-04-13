"""Registry of pipelines defined in the notebook session.

`%%kfp_pipeline` cells register the pipeline function here so that
`kubekit decompile` knows what to operate on without the user having to
pass it around explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from kubekit_jupyter.decorators import PipelineMetadata


@dataclass
class PipelineResult:
    """Result of evaluating a %%kfp_pipeline cell."""
    pipeline_fn: Callable
    metadata: PipelineMetadata
    components: list[str] = field(default_factory=list)
    source: str = ""  # raw cell source, used as a fallback by the decompiler

    def _repr_html_(self) -> str:
        comps = ", ".join(f"<code>{c}</code>" for c in self.components) or "<i>none detected</i>"
        return (
            f"<div style='padding:8px;border-left:3px solid #10b981;'>"
            f"<b style='color:#10b981;'>✓ pipeline <code>{self.metadata.name}</code></b>"
            f"<div style='margin-top:4px;'>owner: {self.metadata.owner}</div>"
            f"<div>components: {comps}</div>"
            f"<div style='margin-top:6px;color:#666;'>run <code>kubekit decompile</code> to produce a production repo.</div>"
            f"</div>"
        )


@dataclass
class ComponentRecord:
    """One entry in the ComponentRegistry — the captured source for a component."""
    name: str
    source: str  # the exact source of the component function as authored
    fn: Any      # the (possibly wrapped) callable


class PipelineRegistry:
    def __init__(self) -> None:
        self._latest: PipelineResult | None = None

    def set_latest(self, result: PipelineResult) -> None:
        self._latest = result

    def latest(self) -> PipelineResult | None:
        return self._latest


class ComponentRegistry:
    """Source-of-truth store for component bodies captured by %%kfp_component.

    The decompiler consumes this to emit real component modules instead of
    NotImplementedError placeholders. Survives across cells in a session but
    is process-local — persistence is a v2 concern.
    """
    def __init__(self) -> None:
        self._by_name: dict[str, ComponentRecord] = {}

    def register(self, record: ComponentRecord) -> None:
        self._by_name[record.name] = record

    def get(self, name: str) -> ComponentRecord | None:
        return self._by_name.get(name)

    def names(self) -> list[str]:
        return list(self._by_name)


_REGISTRY = PipelineRegistry()
_COMPONENTS = ComponentRegistry()


def get_registry() -> PipelineRegistry:
    return _REGISTRY


def get_component_registry() -> ComponentRegistry:
    return _COMPONENTS
