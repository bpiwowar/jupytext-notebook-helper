"""Runtime helpers for authoring jupytext-percent teaching notebooks.

What this module offers is what an *author* needs while writing and checking a
source, not what the notebook itself needs to run:

``print_header``
    A formatted header when the source runs as a script; the jupytext filter
    turns the same call into a markdown header, so it never reaches a built
    notebook.
``NOTEBOOK_OUTPUT``
    Where output goes: ``notebook`` (inline), ``console`` (imgcat + INFO
    logging, what ``make check`` wants) or ``off`` (no figures at all).
    Defaults to the context. See ``jupytext_notebook_helper.output``.

The two questions the *notebook* asks — what this machine offers, and how much
compute to spend on it — belong to `cs-lab <https://pypi.org/project/cs-lab/>`_,
which a student installs and this package does not replace::

    from cs_lab import hardware
    from mycourse.profiles import Profile

    hw = hardware(Profile)
    MODEL = Profile.pick(fast_test="tiny/model", low_gpu="big/model")
    model = load_hf_model(MODEL, AutoModelForCausalLM, dtype=hw.dtype)

Importing this module tells ``hardware()`` to mention figure visibility in the
note it shows, since that is this side's decision to make.

Usage in a cell tagged ``teacher, not-colab``::

    from jupytext_notebook_helper import *
"""

import io
import logging

from jupytext_notebook_helper.output import (  # noqa: F401
    ENV_OUTPUT,
    OutputMode,
    current_output_mode,
    env_output_mode,
    mark_applied,
    set_output_mode,
    skip_figures,
)

__all__ = [
    # where output goes
    "OutputMode",
    "current_output_mode",
    "set_output_mode",
    "print_header",
]

_output_mode = current_output_mode()

# Figures are dropped: pin matplotlib to Agg before anything imports pyplot.
if skip_figures():
    try:
        import matplotlib

        matplotlib.use("Agg")
    except ImportError:  # pragma: no cover - matplotlib is a hard dependency
        pass


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
        if skip_figures():
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
# nothing to patch — the inline backend draws at the end of the cell.
if _output_mode is not OutputMode.NOTEBOOK:
    if _output_mode is OutputMode.CONSOLE:
        logging.basicConfig(
            level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s"
        )
    _patch_matplotlib()

mark_applied(_output_mode)


def _figure_state() -> str:
    """What to add to the note `cs_lab.hardware` shows in a notebook.

    Figure visibility is decided here — it is a start-up decision, made by
    ``NOTEBOOK_OUTPUT`` before anything imports pyplot — so the profile line
    says it only when this package is present, i.e. in a teacher's notebook.
    """
    return f"images: {'shown' if current_output_mode().shows_figures else 'off'}"


try:
    from cs_lab import add_state_note

    add_state_note(_figure_state)
except ImportError:  # pragma: no cover - cs-lab is a declared dependency
    pass
