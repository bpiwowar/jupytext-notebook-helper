"""Runtime helpers for jupytext-percent teaching notebooks.

Extracted from ``master_mind.teaching.utils`` so it can be shared across courses
without depending on the whole master-mind framework.

Provides:
  - ``test_mode`` / ``skip_plots`` driven by the ``TESTING_MODE`` env var,
  - ``print_header`` (formatted header in scripts; jupytext-filter turns it into a
    markdown header in notebooks),
  - ``is_notebook``,
  - automatic patching of ``matplotlib.pyplot.show`` so that, when a notebook is
    executed as a *script* (e.g. ``make check``), figures render inline in the
    terminal via ``imgcat``.

Usage in a (teacher-only) notebook cell::

    from jupytext_notebook_helper import *

Environment variable ``TESTING_MODE``:
  - ``"off"`` (default): full datasets, plots shown normally;
  - ``"on"``: reduced datasets/training, plots still shown;
  - ``"full"``: reduced datasets/training, GUI plots disabled (Agg backend).
"""

import io
import logging
import os
import sys

__all__ = ["test_mode", "skip_plots", "print_header", "is_notebook"]

# Parse testing mode from environment
test_mode_value = os.environ.get("TESTING_MODE", "off").lower()
test_mode = test_mode_value in ["on", "full"]
skip_plots = test_mode_value == "full"

if test_mode:
    print(f"#># Testing mode: {test_mode_value}", file=sys.stderr)  # noqa: T201

# Disable matplotlib GUI when in full test mode
if skip_plots:
    import matplotlib

    matplotlib.use("Agg")  # Non-interactive backend


def print_header(title: str):
    """Print a section header.

    In Python script mode, prints a formatted header with separators. In notebook
    mode this call is converted to a markdown header by jupytext-filter.
    """
    print("=" * 80)  # noqa: T201
    print(title)  # noqa: T201
    print("=" * 80)  # noqa: T201


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


def _display_image_terminal(img, title: str = None):
    """Display a single image in the terminal using imgcat (iTerm2/Kitty/VSCode)."""
    if title:
        print(f"\n{title}")  # noqa: T201
    try:
        import imgcat

        imgcat.imgcat(img)
        return
    except ImportError:
        pass
    if getattr(img, "filename", None):
        print(f"  [Image: {img.filename}]")  # noqa: T201
    else:
        print("  [Image displayed - install 'imgcat' for terminal preview]")  # noqa: T201


def _patch_matplotlib():
    """Patch ``plt.show()`` to render figures in the terminal via imgcat."""
    import matplotlib.pyplot as plt

    _original_show = plt.show

    def _patched_show(*args, **kwargs):
        fig = plt.gcf()
        if fig.axes:
            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
            buf.seek(0)
            try:
                import imgcat
                from PIL import Image

                imgcat.imgcat(Image.open(buf))
                plt.close("all")
                return
            except ImportError:
                print("[Plot rendered - install 'imgcat' for terminal preview]")  # noqa: T201
        if not skip_plots:
            _original_show(*args, **kwargs)
        else:
            plt.close("all")

    plt.show = _patched_show


# When running as a script (not in a notebook), enable INFO logging and route
# matplotlib figures to the terminal.
if not is_notebook():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    _patch_matplotlib()
