"""Tests for templates, examples, and the walkthrough.

The invariant that matters most: every template and example must be
syntactically valid Python after stripping the magic header. A template
that doesn't parse is a template that will fail at shift-enter, which is
the worst possible first experience for a new user.
"""
from __future__ import annotations

import ast

import pytest

from kubekit_jupyter.templates import (
    EXAMPLES,
    WALKTHROUGH,
    list_examples,
    render_component,
    render_example,
    render_pipeline,
)
from kubekit_jupyter.validators import validate_component_source
from kubekit_jupyter.results import Severity


def _strip_magic(cell: str) -> str:
    lines = cell.splitlines()
    if lines and lines[0].startswith("%%"):
        lines = lines[1:]
    return "\n".join(lines)


def test_component_template_parses():
    body = _strip_magic(render_component("my_loader"))
    ast.parse(body)  # raises on failure


def test_pipeline_template_parses():
    body = _strip_magic(render_pipeline("my_pipeline", "you@example.com"))
    ast.parse(body)


def test_component_template_passes_validation():
    """A freshly-scaffolded component should never trip the rules engine.

    This is the 'new user sees a green checkmark on first run' invariant.
    """
    body = _strip_magic(render_component("my_loader"))
    findings = validate_component_source(body)
    errors = [f for f in findings if f.severity == Severity.ERROR]
    assert errors == [], f"template produced errors: {[f.rule for f in errors]}"


def test_component_template_substitutes_name():
    cell = render_component("velocity_loader")
    assert "def velocity_loader(" in cell


def test_pipeline_template_substitutes_name_and_owner():
    cell = render_pipeline("fraud_v2", "dan@capitalone.com")
    assert 'name="fraud_v2"' in cell
    assert 'owner="dan@capitalone.com"' in cell
    assert "def fraud_v2(" in cell


def test_list_examples_returns_all_topics():
    topics = list_examples()
    assert set(topics) == set(EXAMPLES.keys())
    assert "artifact" in topics
    assert "snowflake" in topics


def test_render_example_unknown_topic_returns_none():
    assert render_example("not-a-topic") is None


@pytest.mark.parametrize("topic", list(EXAMPLES.keys()))
def test_every_example_parses(topic: str):
    """Every example must parse as valid Python after magic stripping.

    Parameterizing on EXAMPLES means adding a new example automatically
    adds a test.
    """
    body = _strip_magic(EXAMPLES[topic])
    try:
        ast.parse(body)
    except SyntaxError as e:
        pytest.fail(f"example {topic!r} does not parse: {e}")


def test_walkthrough_mentions_core_magics():
    assert "%kfp_new" in WALKTHROUGH
    assert "%kfp_decompile" in WALKTHROUGH
    assert "%kfp_standards" in WALKTHROUGH
