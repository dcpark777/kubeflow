"""Typed result objects returned by magics.

Each magic returns a result with a rich _repr_html_ for notebook display
and a scriptable API so advanced users can chain operations:

    result = %kfp_submit my_pipeline
    result.wait()
    result.explain()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


@dataclass
class Finding:
    """A single issue raised by a validator."""
    severity: Severity
    rule: str
    message: str
    suggestion: str | None = None
    why: str | None = None  # optional longer explanation for new users
    line: int | None = None

    def _repr_html_(self) -> str:
        color = {"info": "#3b82f6", "warn": "#f59e0b", "error": "#ef4444"}[self.severity.value]
        icon = {"info": "ℹ", "warn": "⚠", "error": "✗"}[self.severity.value]
        suggestion = f"<div style='margin-top:4px;color:#666;'>→ {self.suggestion}</div>" if self.suggestion else ""
        why = ""
        if self.why:
            why = (
                f"<details style='margin-top:4px;'>"
                f"<summary style='cursor:pointer;color:#888;'>why this rule exists</summary>"
                f"<div style='margin-top:4px;padding:6px;background:#f9f9f9;color:#555;'>{self.why}</div>"
                f"</details>"
            )
        return (
            f"<div style='padding:8px;border-left:3px solid {color};margin:4px 0;'>"
            f"<b style='color:{color};'>{icon} {self.rule}</b>"
            f"<div>{self.message}</div>{suggestion}{why}</div>"
        )


@dataclass
class ComponentResult:
    """Result of validating a KFP component cell."""
    component: Any  # the decorated KFP component function
    findings: list[Finding] = field(default_factory=list)
    source: str = ""

    @property
    def ok(self) -> bool:
        return not any(f.severity == Severity.ERROR for f in self.findings)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.WARN]

    def explain(self) -> str:
        """Use Claude to explain findings in plain English. Optional dep."""
        from kubekit_jupyter.validators import explain_findings
        return explain_findings(self.findings, self.source)

    def _repr_html_(self) -> str:
        if self.ok and not self.findings:
            name = getattr(self.component, "name", "component")
            return (
                f"<div style='padding:8px;border-left:3px solid #10b981;'>"
                f"<b style='color:#10b981;'>✓ component <code>{name}</code> validated</b></div>"
            )
        header = f"<div><b>{len(self.errors)} errors, {len(self.warnings)} warnings</b></div>"
        body = "".join(f._repr_html_() for f in self.findings)
        return f"<div>{header}{body}</div>"
