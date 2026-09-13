"""Detect whether code is running inside a Jupyter kernel."""

from __future__ import annotations

__all__ = ["is_notebook"]


def is_notebook() -> bool:
    """Return True if running inside a Jupyter notebook (ZMQInteractiveShell)."""
    try:
        from IPython import get_ipython

        shell = get_ipython()
        if shell is None:
            return False
        return shell.__class__.__name__ == "ZMQInteractiveShell"
    except (ImportError, AttributeError):
        return False
