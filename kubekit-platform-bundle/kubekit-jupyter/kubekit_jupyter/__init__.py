"""kubekit-jupyter: Jupyter magics for KFP v2 authoring with kubekit.

Load with: %load_ext kubekit_jupyter

Exports:
    pipeline — the @kubekit.pipeline decorator (name=, owner=)
"""
from kubekit_jupyter.decorators import pipeline


def load_ipython_extension(ipython):
    """Entry point called by IPython when %load_ext kubekit_jupyter runs."""
    from kubekit_jupyter.magics import KubekitMagics
    ipython.register_magics(KubekitMagics)


__all__ = ["load_ipython_extension", "pipeline"]
