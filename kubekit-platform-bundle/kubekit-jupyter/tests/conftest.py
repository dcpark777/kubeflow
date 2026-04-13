"""Shared fixtures.

The tests avoid importing `kubekit_jupyter` at the package level because
that triggers the magics module which pulls in IPython. Instead each test
imports the specific submodules it needs directly.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_registries():
    """Clear the pipeline and component registries before each test.

    The registries are process-global, so without this tests would leak
    state into each other and break assertions about missing components.
    """
    from kubekit_jupyter.pipeline import get_component_registry, get_registry
    get_registry().set_latest(None)
    get_component_registry()._by_name.clear()
    yield


@pytest.fixture
def fake_kfp():
    """Install a minimal fake `kfp` module so component cells can exec.

    Real KFP is a heavy dependency and we don't want the test suite to
    require it. The fake provides just enough surface for decorator calls
    to succeed.
    """
    class _Dsl:
        @staticmethod
        def component(**kwargs):
            def deco(fn):
                return fn
            return deco

        @staticmethod
        def pipeline(*args, **kwargs):
            def deco(fn):
                return fn
            return deco

    fake = types.SimpleNamespace(dsl=_Dsl())
    sys.modules["kfp"] = fake
    yield fake
    sys.modules.pop("kfp", None)


@pytest.fixture
def tmp_out(tmp_path: Path) -> Path:
    """A throwaway output directory for decompile tests."""
    return tmp_path / "out"
