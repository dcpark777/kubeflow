"""The @kubekit.pipeline decorator.

A two-kwarg wrapper over @dsl.pipeline that captures the name and owner
metadata the decompiler needs. Everything else the decompiler needs is
already implicit in the compiled pipeline spec.

Intended to live at kubekit.pipeline in the real kubekit library. For
this v1 prototype we ship it from kubekit_jupyter.decorators and re-export.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class PipelineMetadata:
    name: str
    owner: str


def pipeline(*, name: str, owner: str) -> Callable:
    """Decorate a KFP pipeline function with name and owner metadata.

    Usage:
        @kubekit.pipeline(name="fraud_velocity", owner="dan@capitalone.com")
        @dsl.pipeline
        def training_pipeline(train_date: str):
            ...

    The metadata is attached to the function as __kubekit_metadata__ and
    consumed by `kubekit decompile` when it generates the production repo.
    """
    def decorator(fn: Callable) -> Callable:
        fn.__kubekit_metadata__ = PipelineMetadata(name=name, owner=owner)
        return fn
    return decorator
