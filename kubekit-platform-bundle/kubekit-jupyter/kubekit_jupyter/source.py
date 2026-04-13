"""Extract the exact source of a named function from a cell or file.

Used by %%kfp_component to capture component bodies for the decompiler.
Prefers inspect.getsource() when it works and falls back to AST-based
extraction from the raw cell text otherwise.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Callable


def extract_function_source(fn: Callable, fallback_cell: str | None = None) -> str:
    """Return the source of `fn` as a string, dedented.

    Tries inspect.getsource() first; on failure, falls back to extracting
    the function from the raw cell text by AST. Returns an empty string
    if both paths fail.
    """
    # Unwrap functools.wraps so we see the original function.
    target = inspect.unwrap(fn) if hasattr(fn, "__wrapped__") else fn

    try:
        src = inspect.getsource(target)
        return textwrap.dedent(src)
    except (OSError, TypeError):
        pass

    if fallback_cell is not None:
        src = extract_function_source_from_text(target.__name__, fallback_cell)
        if src:
            return src

    return ""


def extract_function_source_from_text(name: str, text: str) -> str:
    """Extract the source of a top-level function by name from a text block.

    Includes decorators — `ast.get_source_segment` on a FunctionDef returns
    only the function body, not its decorators, so we walk back to the first
    decorator's line to capture the full declaration as the user wrote it.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ""

    lines = text.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            start_line = node.lineno
            if node.decorator_list:
                start_line = min(d.lineno for d in node.decorator_list)
            end_line = getattr(node, "end_lineno", None) or node.lineno
            segment = "".join(lines[start_line - 1:end_line])
            return textwrap.dedent(segment)
    return ""
