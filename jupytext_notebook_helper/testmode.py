"""Test mode: the ``off`` / ``on`` / ``full`` fidelity levels, plus the
(teacher-only) chooser that switches between them *from* a notebook.

What is switchable at run time, and what is not
-----------------------------------------------

``test_mode`` only ever reaches the notebook through ``if test_mode:`` guards
that shrink a dataset or a training loop. Nothing is cached: a cell run *after*
the switch simply reads the new value. So ``test_mode`` is switchable, provided
the value is read **live** rather than captured at import — hence ``test_mode``
is no longer a plain ``bool`` but a small proxy whose ``__bool__`` asks for the
current mode (it still behaves like a bool everywhere else: ``if``, ``not``,
``==``, ``int()``, f-strings). What cannot be undone is the past: cells already
executed keep whatever sizes they computed, so the choice belongs at the top of
the notebook, before the compute cells.

``skip_plots`` is a different story. The ``full`` mode drops figures by pinning
matplotlib to ``Agg`` *at import*, and in a notebook figures are rendered by the
inline backend at the end of each cell -- not by the ``plt.show()`` this package
patches (that patch is script-only). Changing the backend mid-kernel does not
reliably restore, or suppress, inline rendering. Figure suppression is therefore
**not** hot-switchable inside a notebook: it is a start-up decision
(``TESTING_MODE=full``, ``SKIP_PLOTS=1``), which is exactly how ``make check`` /
``make check-ipynb`` use it. The notebook chooser only offers ``off`` / ``on``
for that reason; ``set_test_mode("full")`` in a notebook warns that the figures
stay as they are.

Priority of the environment variable
------------------------------------

``TESTING_MODE``, when set, gives the **initial** mode and suppresses the
automatic chooser: a kernel started with ``TESTING_MODE=full`` (``make
check-ipynb``) or a plain script run behaves exactly as before, no widget, no
prompt, no extra output. It is not a lock: an explicit ``set_test_mode(...)`` /
``select_test_mode()`` from the teacher still wins, because a locked value would
defeat the whole point under ``make lab-test``. Nothing outside a notebook ever
calls those, so non-interactive runs remain env-driven.
"""

from __future__ import annotations

import os
import sys
import warnings
from typing import Any, Callable, Optional, Sequence

from jupytext_notebook_helper import output

__all__ = [
    "MODES",
    "SWITCHABLE_MODES",
    "MODE_DESCRIPTIONS",
    "test_mode",
    "skip_plots",
    "current_test_mode",
    "set_test_mode",
    "select_test_mode",
    "is_notebook",
]

#: The three fidelity levels.
MODES = ("off", "on", "full")

#: Levels the in-notebook chooser may switch to (see the module docstring:
#: ``full`` also turns figures off, which a running kernel cannot undo).
SWITCHABLE_MODES = ("off", "on")

#: One-line description of each level (used in messages and widget labels).
MODE_DESCRIPTIONS = {
    "off": "full datasets, figures shown",
    "on": "reduced datasets/training, figures shown",
    "full": "reduced datasets/training, no figures",
}


def _mode_label(mode: str) -> str:
    """``"on — reduced datasets/training, figures shown"``."""
    return f"{mode} — {MODE_DESCRIPTIONS[mode]}"


_TRUTHY = ("1", "true", "yes", "on")


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


def _parse_mode(value: Any) -> str:
    """Normalise a mode given as a string or a bool."""
    if value is True:
        return "on"
    if value is False:
        return "off"
    mode = str(value).strip().lower()
    if mode not in MODES:
        raise ValueError(f"Unknown testing mode {value!r} (expected one of {MODES})")
    return mode


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

#: Raw value of TESTING_MODE at import (None when unset), and the mode it means.
_env_raw: Optional[str] = os.environ.get("TESTING_MODE")
_env_mode: Optional[str] = None
if _env_raw is not None and _env_raw.strip():
    try:
        _env_mode = _parse_mode(_env_raw)
    except ValueError:
        print(  # noqa: T201
            f"#># Ignoring TESTING_MODE={_env_raw!r} (expected one of {MODES})",
            file=sys.stderr,
        )

_mode: str = _env_mode or "off"

#: SKIP_PLOTS suppresses figures on its own, without touching ``test_mode``.
_skip_plots_env: bool = os.environ.get("SKIP_PLOTS", "").lower() in _TRUTHY

# `TESTING_MODE=full` meant "small datasets *and* no figures". Those are two
# different questions, so `full` now only seeds the output half; the sizing half
# is `NOTEBOOK_PROFILE`. Done once, here, so `output` owes nothing to this module.
if _env_mode == "full" and output.env_output_mode() is None:
    output.set_output_mode(output.OutputMode.OFF, verbose=False)

#: Warn about `test_mode` once per session rather than on every read.
_deprecation_warned = False


def _warn_deprecated(what: str) -> None:
    global _deprecation_warned
    if _deprecation_warned:
        return
    _deprecation_warned = True
    warnings.warn(
        f"{what} is deprecated: how much work to do is now a "
        "cached_hub.Profile ladder (NOTEBOOK_PROFILE), and where output goes "
        "is NOTEBOOK_OUTPUT",
        DeprecationWarning,
        stacklevel=3,
    )


def current_test_mode() -> str:
    """Return the current mode: ``"off"``, ``"on"`` or ``"full"``."""
    return _mode


def env_test_mode() -> Optional[str]:
    """Return the mode requested by ``TESTING_MODE``, or None if unset."""
    return _env_mode


def _test_mode_value() -> bool:
    # Exactly the old meaning. Deriving it from whichever profile ladder was
    # last touched would make an unrelated course's ladder change this flag,
    # which is far too surprising for a name that only exists to keep working.
    _warn_deprecated("test_mode")
    return _mode in ("on", "full")


def _skip_plots_value() -> bool:
    # SKIP_PLOTS still forces figures off on its own; everything else is now
    # the output axis.
    return _skip_plots_env or output.skip_figures()


# ---------------------------------------------------------------------------
# Live boolean proxy
# ---------------------------------------------------------------------------


class LiveFlag:
    """A boolean read *at use time* instead of at import time.

    Behaves like the ``bool`` it replaces in every context the notebooks use --
    ``if flag:``, ``not flag``, ``x if flag else y``, ``flag == True``,
    ``int(flag)``, ``f"{flag}"``, ``print(flag)`` -- but consults the current
    state on each access, so a mode chosen from a widget affects the cells run
    afterwards. The one behaviour it cannot reproduce is ``flag is True``.
    """

    __slots__ = ("_name", "_getter")

    def __init__(self, name: str, getter: Callable[[], bool]):
        self._name = name
        self._getter = getter

    # -- truthiness ---------------------------------------------------------
    def __bool__(self) -> bool:
        return bool(self._getter())

    # -- display ------------------------------------------------------------
    def __repr__(self) -> str:
        return repr(bool(self))

    def __str__(self) -> str:
        return str(bool(self))

    def __format__(self, spec: str) -> str:
        return format(bool(self), spec)

    # -- comparison ---------------------------------------------------------
    def __eq__(self, other: Any) -> Any:
        if isinstance(other, LiveFlag):
            return bool(self) == bool(other)
        if isinstance(other, (bool, int, float)):
            return bool(self) == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(bool(self))

    # -- numeric ------------------------------------------------------------
    def __int__(self) -> int:
        return int(bool(self))

    def __index__(self) -> int:
        return int(bool(self))

    def __float__(self) -> float:
        return float(bool(self))

    # -- bitwise (``flag & other``, ``other | flag``, ``~flag``) -------------
    def __and__(self, other: Any) -> Any:
        return bool(self) and bool(other)

    __rand__ = __and__

    def __or__(self, other: Any) -> Any:
        return bool(self) or bool(other)

    __ror__ = __or__

    def __xor__(self, other: Any) -> Any:
        return bool(self) != bool(other)

    __rxor__ = __xor__

    def __invert__(self) -> bool:
        return not bool(self)


#: Truthy in ``on`` and ``full``: reduce datasets / training.
test_mode = LiveFlag("test_mode", _test_mode_value)

#: Truthy in ``full`` or with ``SKIP_PLOTS=1``: drop every figure.
skip_plots = LiveFlag("skip_plots", _skip_plots_value)


# ---------------------------------------------------------------------------
# Switching
# ---------------------------------------------------------------------------


def _apply_plot_backend() -> None:
    """Pin matplotlib to a non-interactive backend when figures are dropped."""
    if not bool(skip_plots):
        return
    try:
        import matplotlib
    except ImportError:  # pragma: no cover - matplotlib is a hard dependency
        return
    matplotlib.use("Agg")


def _plots_are_frozen() -> bool:
    """True when figure rendering can no longer be (un)suppressed.

    In a notebook, figures go through the inline backend at the end of a cell,
    chosen when matplotlib was first imported; the ``plt.show()`` patch this
    package installs is script-only. See the module docstring.
    """
    return is_notebook()


def set_test_mode(mode: Any, *, verbose: bool = True) -> str:
    """Switch the testing mode; return the mode actually in force.

    ``mode`` is ``"off"``, ``"on"``, ``"full"`` (or a bool, mapped to
    ``on``/``off``). Cells executed *after* this call see the new value through
    ``test_mode``; cells already executed are of course unaffected.

    Figure suppression (``full``) is a start-up decision inside a notebook: it is
    reported but not applied there, with a message saying so.
    """
    global _mode

    _warn_deprecated("set_test_mode")
    new_mode = _parse_mode(mode)
    previous_skip = bool(skip_plots)
    _mode = new_mode
    # `full` is the only one of the three that ever meant anything about output.
    output.set_output_mode(
        output.OutputMode.OFF if new_mode == "full" else output.default_output_mode(),
        verbose=False,
    )
    new_skip = bool(skip_plots)

    if new_skip != previous_skip:
        if _plots_are_frozen():
            # The mode itself still switches: only the figures stay put.
            if verbose:
                remedy = (
                    "restart the kernel without TESTING_MODE=full / SKIP_PLOTS=1"
                    if previous_skip
                    else "restart the kernel with TESTING_MODE=full (or SKIP_PLOTS=1)"
                )
                print(  # noqa: T201
                    "#># Figures stay "
                    + ("off" if previous_skip else "on")
                    + " for this kernel: the matplotlib backend is fixed at "
                    f"start-up — {remedy}.",
                    file=sys.stderr,
                )
        else:
            _apply_plot_backend()

    if verbose:
        print(  # noqa: T201
            f"#># Testing mode: {new_mode} ({MODE_DESCRIPTIONS[new_mode]})",
            file=sys.stderr,
        )
    return _mode


# ---------------------------------------------------------------------------
# The notebook chooser
# ---------------------------------------------------------------------------


def _widgets_enabled() -> bool:
    """False when TESTING_MODE_WIDGET is set to a falsy value."""
    value = os.environ.get("TESTING_MODE_WIDGET", "").strip().lower()
    return value == "" or value in _TRUTHY


def _fallback_hint() -> str:
    return (
        f"#># Testing mode: {current_test_mode()} — "
        'call set_test_mode("on") to reduce datasets/training '
        "(install ipywidgets for a toggle)."
    )


def select_test_mode(
    *,
    modes: Sequence[str] = SWITCHABLE_MODES,
    auto: bool = False,
) -> str:
    """Offer the teacher a mode chooser, and return the current mode.

    In a notebook with ``ipywidgets`` installed, displays a toggle; picking a
    value calls :func:`set_test_mode`. Without ``ipywidgets``, prints a one-line
    hint pointing at :func:`set_test_mode`. Outside a notebook it does nothing at
    all (no widget, no prompt, never blocking) -- scripts and ``make check`` stay
    driven by ``TESTING_MODE``.

    ``auto=True`` is the automatic call made at import; it is silent when the
    chooser has been disabled or when ``TESTING_MODE`` was set explicitly.
    """
    if not is_notebook():
        return current_test_mode()

    if auto and (_env_mode is not None or not _widgets_enabled()):
        return current_test_mode()

    for mode in modes:
        _parse_mode(mode)

    try:
        import ipywidgets as widgets
        from IPython.display import display
    except ImportError:
        print(_fallback_hint(), file=sys.stderr)  # noqa: T201
        return current_test_mode()

    current = current_test_mode()
    toggle = widgets.ToggleButtons(
        options=[(_mode_label(m), m) for m in modes],
        value=current if current in modes else modes[0],
        description="Test mode:",
    )
    output = widgets.Output()

    note = (
        "Teacher-only. Applies to the cells run <b>after</b> this point — "
        "re-run the cells above to resize what they already computed."
    )
    if current not in modes:
        note += (
            f" Started as <code>{current}</code> "
            "(<code>TESTING_MODE</code>); switching leaves the figures as they are."
        )
    else:
        note += (
            " Dropping the figures (<code>full</code>) is a start-up choice: "
            "<code>TESTING_MODE=full</code>."
        )
    if _env_mode is not None:
        note += f" <code>TESTING_MODE={_env_mode}</code> in the environment."

    def _on_change(change: dict) -> None:
        if change.get("name") != "value" or change["new"] == change["old"]:
            return
        with output:
            output.clear_output()
            set_test_mode(change["new"])

    toggle.observe(_on_change, names="value")
    display(widgets.VBox([toggle, widgets.HTML(note), output]))
    return current_test_mode()


def _auto_select() -> None:
    """Called once, at package import, from a (teacher) notebook cell."""
    try:
        select_test_mode(auto=True)
    except Exception as exc:  # pragma: no cover - never break the import
        print(f"#># Test-mode chooser unavailable: {exc}", file=sys.stderr)  # noqa: T201


def _reset_for_tests(
    mode: str = "off",
    *,
    env_mode: Optional[str] = None,
    skip_plots_env: bool = False,
) -> None:
    """Restore a known state (used by the test-suite)."""
    global _mode, _env_mode, _skip_plots_env, _deprecation_warned
    _mode = _parse_mode(mode)
    _env_mode = None if env_mode is None else _parse_mode(env_mode)
    _skip_plots_env = skip_plots_env
    _deprecation_warned = False
    output._reset_for_tests()
    if _mode == "full":
        output.set_output_mode(output.OutputMode.OFF, verbose=False)
