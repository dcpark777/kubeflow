"""Tests for the validator rules engine.

Each test exercises exactly one rule with the smallest possible cell.
Adding a rule means adding one test here.
"""
from __future__ import annotations

from kubekit_jupyter.results import Severity
from kubekit_jupyter.validators import validate_component_source


def _rules(findings) -> set[str]:
    return {f.rule for f in findings}


def test_clean_component_has_no_findings():
    src = '''
from kfp import dsl

@dsl.component(cpu="500m", memory="2Gi")
def clean(x: str) -> str:
    from kubekit.logging import get_logger
    log = get_logger(__name__)
    log.info("start", x=x)
    return x
'''
    assert validate_component_source(src) == []


def test_missing_decorator_is_error():
    src = "def train(data: str) -> str:\n    return data\n"
    findings = validate_component_source(src)
    assert "missing-decorator" in _rules(findings)
    assert any(f.severity == Severity.ERROR for f in findings)


def test_empty_cell_is_error():
    findings = validate_component_source("x = 1\n")
    assert "no-component" in _rules(findings)


def test_missing_resources_is_warning():
    src = '''
from kfp import dsl

@dsl.component
def train(data: str) -> str:
    return data
'''
    findings = validate_component_source(src)
    assert "missing-resources" in _rules(findings)
    rule = next(f for f in findings if f.rule == "missing-resources")
    assert rule.severity == Severity.WARN


def test_missing_annotation_is_error():
    src = '''
from kfp import dsl

@dsl.component(cpu="500m", memory="2Gi")
def train(data) -> str:
    return data
'''
    findings = validate_component_source(src)
    assert "missing-annotation" in _rules(findings)


def test_bare_print_is_warning():
    src = '''
from kfp import dsl

@dsl.component(cpu="500m", memory="2Gi")
def train(data: str) -> str:
    print("hello")
    return data
'''
    findings = validate_component_source(src)
    assert "bare-print" in _rules(findings)


def test_hardcoded_secret_is_error():
    src = '''
from kfp import dsl

@dsl.component(cpu="500m", memory="2Gi")
def train(data: str) -> str:
    api_key = "sk-live-abc123"
    return data
'''
    findings = validate_component_source(src)
    assert "hardcoded-secret" in _rules(findings)
    rule = next(f for f in findings if f.rule == "hardcoded-secret")
    assert rule.severity == Severity.ERROR


def test_syntax_error_returns_single_finding():
    findings = validate_component_source("def bad(:\n")
    assert len(findings) == 1
    assert findings[0].rule == "syntax"


def test_every_rule_has_a_why_explanation():
    """Every finding the engine can produce should carry a 'why' paragraph.

    This is the self-teaching invariant — new users learn by reading
    why rules exist, so any rule that ships without a why is a regression.
    """
    cells = [
        "def train(x: str):\n    return x\n",  # missing-decorator
        'from kfp import dsl\n@dsl.component\ndef train(x: str):\n    return x\n',  # missing-resources
        'from kfp import dsl\n@dsl.component(cpu="500m", memory="2Gi")\ndef train(x):\n    return x\n',  # missing-annotation
        'from kfp import dsl\n@dsl.component(cpu="500m", memory="2Gi")\ndef train(x: str):\n    print(x)\n    return x\n',  # bare-print
        'from kfp import dsl\n@dsl.component(cpu="500m", memory="2Gi")\ndef train(x: str):\n    api_key = "sk-abc"\n    return x\n',  # hardcoded-secret
    ]
    for cell in cells:
        findings = validate_component_source(cell)
        non_trivial = [f for f in findings if f.rule not in ("syntax",)]
        assert non_trivial, f"expected findings for cell: {cell!r}"
        for f in non_trivial:
            assert f.why, f"rule {f.rule!r} has no 'why' text"
