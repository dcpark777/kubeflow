"""Tests for the source extractor.

The extractor has the subtlest bug surface in the package — the decorator
bug I caught in manual testing would have stripped resource specs silently.
These tests pin the invariants so that kind of regression gets caught.
"""
from __future__ import annotations

from kubekit_jupyter.source import (
    extract_function_source,
    extract_function_source_from_text,
)


def test_extract_simple_function_from_text():
    text = "def foo(x: int) -> int:\n    return x + 1\n"
    src = extract_function_source_from_text("foo", text)
    assert "def foo(x: int) -> int:" in src
    assert "return x + 1" in src


def test_extract_preserves_decorators():
    """Decorators must be included — this is the regression guard."""
    text = '''
from kfp import dsl

@dsl.component(cpu="500m", memory="2Gi")
def train(x: str) -> str:
    return x
'''
    src = extract_function_source_from_text("train", text)
    assert "@dsl.component" in src
    assert 'cpu="500m"' in src
    assert "def train(" in src


def test_extract_preserves_multiple_decorators():
    text = '''
@first
@second(arg=1)
def f(x: int) -> int:
    return x
'''
    src = extract_function_source_from_text("f", text)
    assert "@first" in src
    assert "@second(arg=1)" in src
    assert "def f(" in src


def test_extract_returns_empty_for_unknown_function():
    text = "def other(): pass\n"
    assert extract_function_source_from_text("missing", text) == ""


def test_extract_returns_empty_on_syntax_error():
    assert extract_function_source_from_text("foo", "def foo(:\n") == ""


def test_extract_live_function_via_inspect():
    """When a function has a real source file, inspect.getsource is used."""
    def real_function(x: int) -> int:
        return x + 1

    src = extract_function_source(real_function)
    assert "def real_function" in src


def test_extract_live_function_unwraps_functools_wraps():
    """Traced components are wrapped; the extractor must see the original."""
    import functools

    def underlying(x: int) -> int:
        return x

    @functools.wraps(underlying)
    def wrapper(*args, **kwargs):
        return underlying(*args, **kwargs)

    src = extract_function_source(wrapper)
    assert "def underlying" in src


def test_extract_falls_back_to_cell_text():
    """When inspect.getsource fails (exec'd cell), fallback path must work."""
    cell = '''
from kfp import dsl

@dsl.component(cpu="1", memory="4Gi")
def from_cell(x: str) -> str:
    return x
'''
    ns: dict = {}
    # Provide a fake dsl so the exec doesn't fail.
    ns["dsl"] = type("Dsl", (), {"component": staticmethod(lambda **kw: lambda f: f)})()
    # Strip the import and exec
    body = "\n".join(line for line in cell.splitlines() if not line.startswith("from kfp"))
    exec(body, ns)
    fn = ns["from_cell"]

    src = extract_function_source(fn, fallback_cell=cell)
    assert "@dsl.component" in src
    assert "def from_cell" in src
