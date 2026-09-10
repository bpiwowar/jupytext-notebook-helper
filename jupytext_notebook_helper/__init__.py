"""Runtime helpers for jupytext-percent teaching notebooks.

Extracted from ``master_mind.teaching.utils`` so it can be shared across courses
without depending on the whole master-mind framework.

Provides:
  - ``test_mode`` / ``skip_plots``, seeded from the ``TESTING_MODE`` env var and
    switchable from a (teacher) notebook -- see ``jupytext_notebook_helper.testmode``,
  - ``set_test_mode`` / ``select_test_mode`` / ``current_test_mode``,
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
  - ``"full"``: reduced datasets/training, no figures at all.

When ``TESTING_MODE`` is **not** set and the import happens in a notebook, a
small chooser (``ipywidgets``, optional) is displayed so the teacher can switch
between ``off`` and ``on`` without restarting the kernel or the server; the cells
run afterwards see the new value. When it *is* set, nothing is displayed and the
behaviour is exactly what it has always been (that is what ``make check`` /
``make check-ipynb`` rely on). ``TESTING_MODE_WIDGET=0`` disables the automatic
chooser; ``set_test_mode(...)`` switches by hand at any time.

Environment variable ``SKIP_PLOTS`` (``1``/``true``/``yes``/``on``): suppress every
figure while leaving ``test_mode`` alone — for a full-size run whose log you want
readable (inline images are base64 blobs of a few hundred kB each). Figure
suppression is a *start-up* decision: it cannot be switched from a running
notebook kernel (see ``testmode``).
"""

import io
import logging
import sys

from jupytext_notebook_helper.testmode import (  # noqa: F401
    MODES,
    SWITCHABLE_MODES,
    LiveFlag,
    _apply_plot_backend,
    _auto_select,
    current_test_mode,
    env_test_mode,
    is_notebook,
    select_test_mode,
    set_test_mode,
    skip_plots,
    test_mode,
)

__all__ = [
    "test_mode",
    "skip_plots",
    "print_header",
    "is_notebook",
    "set_test_mode",
    "select_test_mode",
    "current_test_mode",
]

if test_mode:
    print(f"#># Testing mode: {current_test_mode()}", file=sys.stderr)  # noqa: T201

# Disable matplotlib GUI when figures are dropped (``full`` / ``SKIP_PLOTS``)
_apply_plot_backend()


def print_header(title: str):
    """Print a section header.

    In Python script mode, prints a formatted header with separators. In notebook
    mode this call is converted to a markdown header by jupytext-filter.
    """
    print("=" * 80)  # noqa: T201
    print(title)  # noqa: T201
    print("=" * 80)  # noqa: T201


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
        # ``skip_plots`` is read here, not captured: a script that switches mode
        # mid-run (rare, but ``set_test_mode`` allows it) is honoured.
        if skip_plots:
            # Avant tout rendu : imgcat écrivait la figure dans le terminal même
            # en mode « figures désactivées ».
            plt.close("all")
            return

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
        _original_show(*args, **kwargs)

    plt.show = _patched_show


# When running as a script (not in a notebook), enable INFO logging and route
# matplotlib figures to the terminal. In a notebook, offer the teacher the
# test-mode chooser instead (a no-op when TESTING_MODE is set, or outside a
# notebook, or when ipywidgets is missing).
if not is_notebook():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    _patch_matplotlib()
else:
    _auto_select()
