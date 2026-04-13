"""IPython magics exposed by kubekit-jupyter.

Magics:
    %%kfp_component  — validate, execute on success, capture traces
    %%kfp_pipeline   — evaluate a pipeline cell, register it for decompilation
    %kfp_decompile   — decompile the most recent pipeline to a production repo
    %kfp_standards   — print platform standards for a topic
    %kfp_explain     — (stub) explain a failed run id using Claude
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path

from IPython.core.magic import Magics, cell_magic, line_magic, magics_class
from IPython.display import HTML, display

from kubekit_jupyter.decompile import decompile as run_decompile
from kubekit_jupyter.decorators import PipelineMetadata
from kubekit_jupyter.pipeline import (
    ComponentRecord,
    PipelineResult,
    get_component_registry,
    get_registry,
)
from kubekit_jupyter.results import ComponentResult, Severity
from kubekit_jupyter.source import extract_function_source
from kubekit_jupyter.standards import get_standards
from kubekit_jupyter.templates import (
    WALKTHROUGH,
    list_examples,
    render_component,
    render_example,
    render_pipeline,
)
from kubekit_jupyter.traces import Trace, get_store, short_repr
from kubekit_jupyter.validators import validate_component_source


@magics_class
class KubekitMagics(Magics):

    @cell_magic
    def kfp_component(self, line: str, cell: str) -> ComponentResult:
        findings = validate_component_source(cell)
        has_errors = any(f.severity == Severity.ERROR for f in findings)

        if findings:
            display(HTML("".join(f._repr_html_() for f in findings)))

        if has_errors:
            display(HTML(
                "<div style='padding:8px;border-left:3px solid #ef4444;'>"
                "<b style='color:#ef4444;'>Component not executed due to errors.</b></div>"
            ))
            return ComponentResult(component=None, findings=findings, source=cell)

        ns = self.shell.user_ns
        exec(cell, ns)
        component = _find_last_component(ns, cell)

        if component is not None:
            # Capture the authored source before wrapping for tracing.
            src = extract_function_source(component, fallback_cell=cell)
            wrapped = _wrap_for_tracing(component)
            ns[component.__name__] = wrapped
            get_component_registry().register(ComponentRecord(
                name=component.__name__,
                source=src,
                fn=wrapped,
            ))
            component = wrapped

        result = ComponentResult(component=component, findings=findings, source=cell)
        display(result)
        return result

    @cell_magic
    def kfp_pipeline(self, line: str, cell: str):
        ns = self.shell.user_ns
        try:
            exec(cell, ns)
        except Exception as e:
            display(HTML(f"<div style='color:#ef4444;'><b>Error in pipeline cell:</b> {e}</div>"))
            return None

        pipeline_fn = _find_pipeline_function(ns, cell)
        if pipeline_fn is None:
            display(HTML(
                "<div style='color:#ef4444;'>No <code>@kubekit.pipeline</code>-decorated "
                "function found in the cell.</div>"
            ))
            return None

        metadata: PipelineMetadata = pipeline_fn.__kubekit_metadata__
        components = _extract_component_names(cell)
        result = PipelineResult(
            pipeline_fn=pipeline_fn,
            metadata=metadata,
            components=components,
            source=cell,
        )
        get_registry().set_latest(result)
        display(result)
        return result

    @line_magic
    def kfp_decompile(self, line: str) -> None:
        out_dir = line.strip() or "./decompiled"
        result = get_registry().latest()
        if result is None:
            display(HTML(
                "<div style='color:#ef4444;'>No pipeline registered. "
                "Run a <code>%%kfp_pipeline</code> cell first.</div>"
            ))
            return
        display(run_decompile(result, Path(out_dir)))

    @line_magic
    def kfp_walkthrough(self, line: str) -> None:
        """Print the getting-started walkthrough. Run this first if new to KFP."""
        display(HTML(f"<pre style='white-space:pre-wrap;'>{WALKTHROUGH}</pre>"))

    @line_magic
    def kfp_example(self, line: str) -> None:
        """Drop a worked example into the next cell.

        Usage:
            %kfp_example                  (lists available topics)
            %kfp_example <topic>

        Topics: artifact, snowflake, model, params, logger.
        """
        topic = line.strip()
        if not topic:
            items = "".join(f"<li><code>{t}</code></li>" for t in list_examples())
            display(HTML(
                f"<div><b>Available examples:</b><ul>{items}</ul>"
                f"<div style='color:#666;'>Usage: <code>%kfp_example &lt;topic&gt;</code></div></div>"
            ))
            return
        example = render_example(topic)
        if example is None:
            display(HTML(
                f"<div style='color:#ef4444;'>No example for <code>{topic}</code>. "
                f"Available: {', '.join(list_examples())}</div>"
            ))
            return
        self.shell.set_next_input(example, replace=False)
        display(HTML(
            f"<div style='padding:8px;border-left:3px solid #10b981;'>"
            f"<b style='color:#10b981;'>✓ example <code>{topic}</code> ready to edit</b>"
            f"<div style='margin-top:4px;color:#666;'>Review the cell below and adapt it to your needs.</div></div>"
        ))

    @line_magic
    def kfp_new(self, line: str) -> None:
        """Scaffold a new component or pipeline cell.

        Usage:
            %kfp_new component <name>
            %kfp_new pipeline <name>

        The scaffolded cell is dropped into the next cell editor, ready
        to edit. The template embodies the team's standards so that a
        freshly-scaffolded component passes validation on first run.
        """
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            display(HTML(
                "<b>Usage:</b> <code>%kfp_new component &lt;name&gt;</code> "
                "or <code>%kfp_new pipeline &lt;name&gt;</code>"
            ))
            return
        kind, name = parts
        if kind == "component":
            cell = render_component(name)
        elif kind == "pipeline":
            owner = self.shell.user_ns.get("_KUBEKIT_OWNER", "you@example.com")
            cell = render_pipeline(name, owner)
        else:
            display(HTML(
                f"<div style='color:#ef4444;'>Unknown kind <code>{kind}</code>. "
                "Use <code>component</code> or <code>pipeline</code>.</div>"
            ))
            return

        # Drop the scaffolded code into the next cell editor.
        self.shell.set_next_input(cell, replace=False)
        display(HTML(
            f"<div style='padding:8px;border-left:3px solid #10b981;'>"
            f"<b style='color:#10b981;'>✓ scaffolded {kind} <code>{name}</code></b>"
            f"<div style='margin-top:4px;color:#666;'>Edit the cell below and run it.</div></div>"
        ))

    @line_magic
    def kfp_standards(self, line: str) -> None:
        topic = (line or "").strip() or "overview"
        display(HTML(f"<pre style='white-space:pre-wrap;'>{get_standards(topic)}</pre>"))

    @line_magic
    def kfp_explain(self, line: str) -> None:
        run_id = line.strip()
        if not run_id:
            display(HTML("<b>Usage:</b> <code>%kfp_explain &lt;run-id&gt;</code>"))
            return
        display(HTML(f"<div>Would diagnose run <code>{run_id}</code>. Stub in v1.</div>"))


# ---- helpers ---------------------------------------------------------------


def _find_last_component(ns: dict, source: str):
    tree = ast.parse(source)
    names = [n.name for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.decorator_list]
    for name in reversed(names):
        obj = ns.get(name)
        if callable(obj):
            return obj
    return None


def _find_pipeline_function(ns: dict, source: str):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            obj = ns.get(node.name)
            if obj is not None and hasattr(obj, "__kubekit_metadata__"):
                return obj
    return None


def _extract_component_names(source: str) -> list[str]:
    tree = ast.parse(source)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in names and not node.func.id.startswith("_"):
                names.append(node.func.id)
    reserved = {"print", "len", "range", "str", "int", "list", "dict", "set",
                "pipeline", "component", "Input", "Output"}
    return [n for n in names if n not in reserved]


def _wrap_for_tracing(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        result = fn(*args, **kwargs)
        args_repr = {f"arg_{i}": short_repr(a) for i, a in enumerate(args)}
        args_repr.update({k: short_repr(v) for k, v in kwargs.items()})
        get_store().record(Trace(
            component_name=fn.__name__,
            args_repr=args_repr,
            return_repr=short_repr(result) if result is not None else None,
        ))
        return result
    wrapper.__kubekit_wrapped__ = True
    return wrapper
