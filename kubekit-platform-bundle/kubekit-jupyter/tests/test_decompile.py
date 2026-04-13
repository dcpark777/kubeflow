"""End-to-end tests for the decompiler.

These tests drive the decompiler the way the magic would — register
components, build a PipelineResult, call decompile(), and assert on the
files produced. They are the closest thing to a real pilot without a
live notebook.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kubekit_jupyter.decompile import decompile
from kubekit_jupyter.decorators import pipeline as pipeline_decorator
from kubekit_jupyter.pipeline import (
    ComponentRecord,
    PipelineResult,
    get_component_registry,
)
from kubekit_jupyter.traces import Trace, get_store


def _make_pipeline_result(
    *,
    name: str = "test_pipeline",
    owner: str = "test@example.com",
    components: list[str] | None = None,
    source: str = "",
) -> PipelineResult:
    @pipeline_decorator(name=name, owner=owner)
    def test_pipeline(train_date: str = "2026-04-01"):
        pass

    return PipelineResult(
        pipeline_fn=test_pipeline,
        metadata=test_pipeline.__kubekit_metadata__,
        components=components or [],
        source=source,
    )


def test_decompile_emits_expected_file_set(tmp_out: Path):
    result = _make_pipeline_result(components=["load_features"])
    get_component_registry().register(ComponentRecord(
        name="load_features",
        source="def load_features(d: str) -> dict:\n    return {}",
        fn=None,
    ))
    decompile_result = decompile(result, tmp_out)

    expected_files = {
        "README.md",
        "NEXT_STEPS.md",
        "Jenkinsfile",
        "pyproject.toml",
        "pipeline.py",
        "components/__init__.py",
        "components/load_features.py",
        "tests/__init__.py",
        "tests/test_load_features.py",
    }
    actual_files = {str(p.relative_to(tmp_out)) for p in decompile_result.files_written}
    assert expected_files.issubset(actual_files)


def test_decompile_component_file_contains_captured_source(tmp_out: Path):
    src = 'def load_features(train_date: str) -> dict:\n    return {"rows": 0}'
    get_component_registry().register(ComponentRecord(
        name="load_features",
        source=src,
        fn=None,
    ))
    result = _make_pipeline_result(components=["load_features"])
    decompile(result, tmp_out)

    content = (tmp_out / "components" / "load_features.py").read_text()
    assert "def load_features(train_date: str) -> dict:" in content
    assert '"rows": 0' in content
    assert "NotImplementedError" not in content


def test_decompile_falls_back_for_missing_components(tmp_out: Path):
    # Register only one of the two components the pipeline references.
    get_component_registry().register(ComponentRecord(
        name="load_features",
        source="def load_features(d: str) -> dict:\n    return {}",
        fn=None,
    ))
    result = _make_pipeline_result(components=["load_features", "train_model"])
    decompile(result, tmp_out)

    missing = (tmp_out / "components" / "train_model.py").read_text()
    assert "NotImplementedError" in missing
    assert "No source captured" in missing

    next_steps = (tmp_out / "NEXT_STEPS.md").read_text()
    assert "train_model" in next_steps
    assert "still need bodies" in next_steps


def test_decompile_next_steps_omits_missing_section_when_all_captured(tmp_out: Path):
    get_component_registry().register(ComponentRecord(
        name="load_features",
        source="def load_features(d: str): return {}",
        fn=None,
    ))
    result = _make_pipeline_result(components=["load_features"])
    decompile(result, tmp_out)

    next_steps = (tmp_out / "NEXT_STEPS.md").read_text()
    assert "still need bodies" not in next_steps


def test_decompile_tests_include_trace_data(tmp_out: Path):
    get_component_registry().register(ComponentRecord(
        name="train_model",
        source="def train_model(data: dict) -> float:\n    return 0.85",
        fn=None,
    ))
    get_store().record(Trace(
        component_name="train_model",
        args_repr={"arg_0": "{'rows': 1000}"},
        return_repr="0.85",
    ))
    result = _make_pipeline_result(components=["train_model"])
    decompile(result, tmp_out)

    test_file = (tmp_out / "tests" / "test_train_model.py").read_text()
    assert "arg_0 = {'rows': 1000}" in test_file
    assert "0.85" in test_file


def test_decompile_tests_skip_when_no_traces(tmp_out: Path):
    get_component_registry().register(ComponentRecord(
        name="untraced",
        source="def untraced(): pass",
        fn=None,
    ))
    result = _make_pipeline_result(components=["untraced"])
    decompile(result, tmp_out)

    test_file = (tmp_out / "tests" / "test_untraced.py").read_text()
    assert "pytest.skip" in test_file


def test_decompile_pipeline_file_uses_recovered_source(tmp_out: Path):
    cell = '''import kubekit_jupyter as kubekit
from kfp import dsl

@kubekit.pipeline(name="recovered", owner="test@example.com")
def my_pipeline(train_date: str = "2026-04-01"):
    return load_features(train_date)
'''
    # Build a PipelineResult whose pipeline_fn is actually named my_pipeline
    # so the text-based extractor can find it in the cell.
    @pipeline_decorator(name="recovered", owner="test@example.com")
    def my_pipeline(train_date: str = "2026-04-01"):
        pass

    result = PipelineResult(
        pipeline_fn=my_pipeline,
        metadata=my_pipeline.__kubekit_metadata__,
        components=["load_features"],
        source=cell,
    )
    get_component_registry().register(ComponentRecord(
        name="load_features",
        source="def load_features(d: str): return {}",
        fn=None,
    ))
    decompile(result, tmp_out)

    pipeline_content = (tmp_out / "pipeline.py").read_text()
    assert "def my_pipeline" in pipeline_content
    assert '"2026-04-01"' in pipeline_content
    assert "from components.load_features" in pipeline_content


def test_decompile_readme_contains_owner_and_name(tmp_out: Path):
    result = _make_pipeline_result(name="fraud_v1", owner="dan@capitalone.com")
    decompile(result, tmp_out)
    readme = (tmp_out / "README.md").read_text()
    assert "fraud_v1" in readme
    assert "dan@capitalone.com" in readme
