"""Runtime helpers for jupytext-percent teaching notebooks.

Extracted from ``master_mind.teaching.utils`` so it can be shared across courses
without depending on the whole master-mind framework.

Two questions a notebook has to answer, kept apart:

``hardware()``
    What this machine offers — device, dtype, and whether ``bitsandbytes`` or
    ``vLLM`` actually work here. See ``jupytext_notebook_helper.machine``.
``NOTEBOOK_OUTPUT``
    Where output goes: ``notebook`` (inline), ``console`` (imgcat + INFO
    logging, what ``make check`` wants) or ``off`` (no figures at all).
    Defaults to the context. See ``jupytext_notebook_helper.output``.

A third question — *how much* compute to spend — belongs to neither: it is a
``cached_hub.Profile`` ladder the course declares, selected with
``NOTEBOOK_PROFILE``. Hand it to ``hardware()`` and the machine picks a sensible
starting rung::

    from jupytext_notebook_helper import hardware
    from mycourse.profiles import Profile

    hw = hardware(Profile)
    MODEL = Profile.pick(fast_test="tiny/model", low_gpu="big/model")
    model = load_hf_model(MODEL, AutoModelForCausalLM, dtype=hw.dtype)

Also provides ``print_header`` (a formatted header in scripts; the jupytext
filter turns it into a markdown header in notebooks) and ``is_notebook``.

Usage in a notebook cell::

    from jupytext_notebook_helper import *

Deprecated: ``test_mode`` / ``skip_plots`` / ``TESTING_MODE``. ``TESTING_MODE``
conflated "use small data" with "draw no figures"; the first is now a profile
and the second is ``NOTEBOOK_OUTPUT``. The old names keep working — courses
still on them are unaffected — and ``TESTING_MODE=full`` still turns figures
off. See ``jupytext_notebook_helper.testmode``.
"""

import io
import logging

from jupytext_notebook_helper.machine import (  # noqa: F401
    ENV_BACKEND,
    Hardware,
    hardware,
)
from jupytext_notebook_helper.output import (  # noqa: F401
    ENV_OUTPUT,
    OutputMode,
    current_output_mode,
    env_output_mode,
    mark_applied,
    set_output_mode,
    skip_figures,
)
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
    # what the machine offers
    "hardware",
    "Hardware",
    # where output goes
    "OutputMode",
    "current_output_mode",
    "set_output_mode",
    "print_header",
    "is_notebook",
    # deprecated: see jupytext_notebook_helper.testmode
    "test_mode",
    "skip_plots",
    "set_test_mode",
    "select_test_mode",
    "current_test_mode",
]

_output_mode = current_output_mode()

# Figures are dropped: pin matplotlib to Agg before anything imports pyplot.
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


# Outside a notebook, turn logging up and route figures through imgcat; with
# output off, the same patch closes them instead. Inside a notebook there is
# nothing to patch — the inline backend draws at the end of the cell — so offer
# the chooser instead (a no-op when the mode is pinned or ipywidgets is absent).
if _output_mode is not OutputMode.NOTEBOOK:
    if _output_mode is OutputMode.CONSOLE:
        logging.basicConfig(
            level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s"
        )
    _patch_matplotlib()
else:
    _auto_select()

mark_applied(_output_mode)
