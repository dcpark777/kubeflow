"""Deterministic validators for KFP v2 components.

The rules engine runs first and finds problems without AI. Each rule is a
small function returning a list of Findings. The AI layer (explain_findings)
is called separately and only on demand — it explains and ranks but does
not find.

Keep rules narrow, pure, and cheap. Adding a rule should be a 10-line change.
"""
from __future__ import annotations

import ast
from typing import Callable

from kubekit_jupyter.results import Finding, Severity

# A rule takes the source string and the parsed AST and returns findings.
Rule = Callable[[str, ast.AST], list[Finding]]

_RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    """Decorator to register a rule."""
    _RULES.append(fn)
    return fn


# ---- Rules --------------------------------------------------------------


@rule
def requires_component_decorator(source: str, tree: ast.AST) -> list[Finding]:
    """The cell must define exactly one @component-decorated function."""
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    if not funcs:
        return [Finding(Severity.ERROR, "no-component",
                        "Cell does not define a function.",
                        "Define one @dsl.component or @kubekit.component function per cell.",
                        why="Every %%kfp_component cell needs to define exactly one component "
                            "function. KFP uses the function to build one unit of work in the "
                            "pipeline DAG — without it there is nothing to execute.")]
    decorated = [f for f in funcs if _has_component_decorator(f)]
    if not decorated:
        return [Finding(Severity.ERROR, "missing-decorator",
                        f"Function {funcs[0].name!r} is not decorated as a KFP component.",
                        "Add @dsl.component or @kubekit.component above the function.",
                        why="A plain Python function is not a KFP component. The @dsl.component "
                            "decorator wraps your function so KFP knows how to containerize it, "
                            "pass it artifacts, and schedule it as part of a pipeline.")]
    return []


@rule
def requires_resource_spec(source: str, tree: ast.AST) -> list[Finding]:
    """Components must declare resource specs. This is a platform convention."""
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef):
            continue
        if not _has_component_decorator(func):
            continue
        decorator = _component_decorator(func)
        kwargs = {kw.arg for kw in getattr(decorator, "keywords", [])}
        if not kwargs & {"cpu", "memory", "resources", "resource_spec"}:
            return [Finding(
                Severity.WARN, "missing-resources",
                f"Component {func.name!r} has no resource spec.",
                "Add cpu= and memory= to the decorator. Platform default is cpu='500m', memory='2Gi'.",
                why="Components without resource specs get scheduled on whatever is available "
                    "and can either starve (too little memory → OOM) or waste the team's quota "
                    "(requesting a whole node for a tiny task). Declaring what you need makes "
                    "your pipeline predictable and helps the platform audit for waste.",
                line=func.lineno,
            )]
    return []


@rule
def typed_parameters(source: str, tree: ast.AST) -> list[Finding]:
    """Component parameters must have type annotations — KFP needs them."""
    findings = []
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef) or not _has_component_decorator(func):
            continue
        for arg in func.args.args:
            if arg.annotation is None:
                findings.append(Finding(
                    Severity.ERROR, "missing-annotation",
                    f"Parameter {arg.arg!r} in {func.name!r} has no type annotation.",
                    "Annotate every component parameter — KFP uses annotations for artifact wiring.",
                    why="KFP uses type annotations to decide whether a parameter is a scalar "
                        "(passed by value) or an artifact (passed by reference). Without the "
                        "annotation, KFP cannot wire the pipeline and submission will fail.",
                    line=arg.lineno,
                ))
    return findings


@rule
def no_bare_prints(source: str, tree: ast.AST) -> list[Finding]:
    """Use the standard logger instead of print — platform standard for observability."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            return [Finding(
                Severity.WARN, "bare-print",
                "Component uses print() instead of the platform logger.",
                "Use `from kubekit.logging import get_logger; log = get_logger(__name__)` and call log.info().",
                why="print() output is unstructured text that gets lost in pod logs. The platform "
                    "logger emits structured events that flow into inference-logger, become "
                    "searchable, and trigger alerts. When something breaks at 2am, structured "
                    "logs are the difference between a fast diagnosis and a long night.",
                line=node.lineno,
            )]
    return []


@rule
def no_hardcoded_secrets(source: str, tree: ast.AST) -> list[Finding]:
    """Catch obvious hardcoded credentials."""
    suspicious = ("password", "secret", "api_key", "token")
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and any(s in target.id.lower() for s in suspicious):
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        findings.append(Finding(
                            Severity.ERROR, "hardcoded-secret",
                            f"Variable {target.id!r} looks like a hardcoded credential.",
                            "Use the platform secret manager or pass via parameter.",
                            why="Credentials in source code end up in git history, container "
                                "images, and log output. Once leaked, they are effectively "
                                "public forever. Use kubekit.secrets.get('name') to retrieve "
                                "secrets at runtime from the platform secret manager.",
                            line=node.lineno,
                        ))
    return findings


# ---- Helpers ------------------------------------------------------------


def _has_component_decorator(func: ast.FunctionDef) -> bool:
    return _component_decorator(func) is not None


def _component_decorator(func: ast.FunctionDef):
    for dec in func.decorator_list:
        name = _decorator_name(dec)
        if name.endswith("component"):
            return dec
    return None


def _decorator_name(dec: ast.expr) -> str:
    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        return dec.attr
    if isinstance(dec, ast.Call):
        return _decorator_name(dec.func)
    return ""


# ---- Engine -------------------------------------------------------------


def validate_component_source(source: str) -> list[Finding]:
    """Run all registered rules against a source string."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [Finding(Severity.ERROR, "syntax", f"Syntax error: {e.msg}", line=e.lineno)]

    findings: list[Finding] = []
    for r in _RULES:
        try:
            findings.extend(r(source, tree))
        except Exception as e:
            findings.append(Finding(Severity.WARN, "rule-error",
                                    f"Rule {r.__name__} failed: {e}"))
    return findings


# ---- AI layer (optional) ------------------------------------------------


def explain_findings(findings: list[Finding], source: str) -> str:
    """Ask Claude to explain the findings in plain English with fix examples.

    Structured prompt + structured output. Claude does not find problems —
    it explains and ranks the ones the rules engine already found.
    """
    try:
        from anthropic import Anthropic
    except ImportError:
        return "Install kubekit-jupyter[ai] to enable AI explanations."

    if not findings:
        return "No findings to explain."

    findings_str = "\n".join(
        f"- [{f.severity.value}] {f.rule}: {f.message}" for f in findings
    )
    prompt = (
        "You are reviewing a KFP v2 component against a platform team's standards. "
        "A rules engine has already found the issues below. Explain each in one "
        "short paragraph and show a minimal code fix. Do not invent additional "
        "issues beyond those listed.\n\n"
        f"Findings:\n{findings_str}\n\n"
        f"Component source:\n```python\n{source}\n```"
    )
    client = Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text
