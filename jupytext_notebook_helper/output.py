"""Where a notebook's output goes: inline, to the terminal, or nowhere.

This is a teacher-facing concern, not a student one. The same source runs in
three places and each wants something different:

``notebook``
    Figures inline, the usual Jupyter behaviour. What a reader gets.
``console``
    The source run as a script (``make check``): figures rendered in the
    terminal through ``imgcat``, and ``logging`` turned up to INFO.
``off``
    No figures at all: matplotlib is pinned to ``Agg`` and ``plt.show()``
    closes instead of drawing. For an automated run whose log should stay
    readable — an inline image is a few hundred kB of base64 per figure.

Left alone, the mode follows the context: ``notebook`` under a kernel,
``console`` otherwise. ``NOTEBOOK_OUTPUT`` overrides it.

This used to be the difference between ``TESTING_MODE=on`` and ``=full``, which
also cut the datasets down. The two have nothing to do with each other — how
much work to do is :class:`cached_hub.Profile`'s question — so they are now
separate knobs.

Choosing the mode is a *start-up* decision: matplotlib's backend cannot be
swapped under a running kernel, so :func:`set_output_mode` reports a change it
cannot apply rather than pretending.

Environment variables
---------------------
``NOTEBOOK_OUTPUT``
    ``notebook``, ``console`` or ``off``. Unparseable values warn and are
    ignored.
``SKIP_PLOTS``
    Legacy: ``1``/``true``/``yes``/``on`` forces ``off``.
"""

import logging
import os
import warnings
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

ENV_OUTPUT = "NOTEBOOK_OUTPUT"
ENV_SKIP_PLOTS = "SKIP_PLOTS"

_TRUTHY = {"1", "true", "yes", "on"}


class OutputMode(Enum):
    """Where figures and logs go."""

    NOTEBOOK = "notebook"
    CONSOLE = "console"
    OFF = "off"

    @property
    def shows_figures(self) -> bool:
        return self is not OutputMode.OFF


MODE_DESCRIPTIONS = {
    OutputMode.NOTEBOOK: "figures inline, as a reader sees them",
    OutputMode.CONSOLE: "figures in the terminal (imgcat), INFO logging",
    OutputMode.OFF: "no figures at all",
}

#: Mode chosen explicitly, winning over the environment.
_explicit: Optional[OutputMode] = None
#: Mode applied at import, so a later change can be reported as ineffective.
_applied: Optional[OutputMode] = None


def _parse(raw: str) -> Optional[OutputMode]:
    try:
        return OutputMode(raw.strip().lower().replace("_", "-"))
    except ValueError:
        return None


def env_output_mode() -> Optional[OutputMode]:
    """Mode named by ``NOTEBOOK_OUTPUT`` (or legacy ``SKIP_PLOTS``)."""
    raw = os.environ.get(ENV_OUTPUT)
    if raw is not None and raw.strip():
        mode = _parse(raw)
        if mode is None:
            logger.warning(
                "ignoring %s=%r; expected one of %s",
                ENV_OUTPUT,
                raw,
                ", ".join(m.value for m in OutputMode),
            )
        else:
            return mode
    legacy = os.environ.get(ENV_SKIP_PLOTS)
    if legacy is not None and legacy.strip().lower() in _TRUTHY:
        return OutputMode.OFF
    return None


def default_output_mode() -> OutputMode:
    """Inline under a kernel, terminal otherwise."""
    from jupytext_notebook_helper.testmode import is_notebook

    return OutputMode.NOTEBOOK if is_notebook() else OutputMode.CONSOLE


def current_output_mode() -> OutputMode:
    """The active mode: explicit choice, else environment, else context."""
    if _explicit is not None:
        return _explicit
    from_env = env_output_mode()
    if from_env is not None:
        return from_env
    return default_output_mode()


def set_output_mode(mode, *, verbose: bool = True) -> OutputMode:
    """Choose the output mode. Warns when the change cannot take effect."""
    global _explicit
    if isinstance(mode, str):
        parsed = _parse(mode)
        if parsed is None:
            raise ValueError(
                f"unknown output mode {mode!r}; expected one of "
                f"{', '.join(m.value for m in OutputMode)}"
            )
        mode = parsed
    _explicit = mode
    if (
        _applied is not None
        and _applied.shows_figures != mode.shows_figures
        and verbose
    ):
        warnings.warn(
            "figure output was already set up as "
            f"{_applied.value!r}; switching to {mode.value!r} needs a restart "
            "to take effect on matplotlib's backend",
            RuntimeWarning,
            stacklevel=2,
        )
    return mode


def skip_figures() -> bool:
    """True when no figure should be drawn at all."""
    return not current_output_mode().shows_figures


def mark_applied(mode: OutputMode) -> None:
    """Record the mode the import-time set-up actually installed."""
    global _applied
    _applied = mode


def _reset_for_tests() -> None:
    global _explicit, _applied
    _explicit = None
    _applied = None
