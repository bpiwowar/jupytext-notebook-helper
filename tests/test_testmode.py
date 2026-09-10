"""Unit tests for the switchable test mode (`jupytext_notebook_helper.testmode`).

Covered here: the semantics of the live boolean proxy, the priority of the
``TESTING_MODE`` environment variable, the behaviour outside a notebook (never a
widget, never a prompt) and the fallback when ``ipywidgets`` is missing.
"""

import builtins
import os
import subprocess
import sys
import types

import pytest

from jupytext_notebook_helper import testmode as tm


@pytest.fixture(autouse=True)
def reset_state():
    """Every test starts from `off`, no env var, and leaves it that way."""
    tm._reset_for_tests("off")
    yield
    tm._reset_for_tests("off")


# ---------------------------------------------------------------------------
# LiveFlag semantics
# ---------------------------------------------------------------------------


def test_flag_is_falsy_in_off_mode():
    assert not tm.test_mode
    assert bool(tm.test_mode) is False
    assert not tm.skip_plots


def test_flag_follows_the_mode_in_if_and_not():
    tm.set_test_mode("on", verbose=False)
    assert tm.test_mode
    assert not (not tm.test_mode)
    taken = "reduced" if tm.test_mode else "full"
    assert taken == "reduced"

    tm.set_test_mode("off", verbose=False)
    assert not tm.test_mode
    taken = "reduced" if tm.test_mode else "full"
    assert taken == "full"


def test_flag_in_fstring_str_repr_and_print(capsys):
    assert f"{tm.test_mode}" == "False"
    assert str(tm.test_mode) == "False"
    assert repr(tm.test_mode) == "False"
    print(tm.test_mode)
    assert capsys.readouterr().out.strip() == "False"

    tm.set_test_mode("on", verbose=False)
    assert f"{tm.test_mode}" == "True"
    assert repr(tm.test_mode) == "True"


def test_flag_comparisons():
    assert tm.test_mode == False  # noqa: E712
    assert tm.test_mode != True  # noqa: E712
    assert (tm.test_mode == True) is False  # noqa: E712
    tm.set_test_mode("on", verbose=False)
    assert tm.test_mode == True  # noqa: E712
    assert tm.test_mode != False  # noqa: E712
    assert tm.test_mode == 1
    assert tm.test_mode != "on"  # unrelated type: not equal, no exception


def test_flag_numeric_and_bitwise():
    assert int(tm.test_mode) == 0
    assert [10, 20][tm.test_mode] == 10  # __index__
    assert (tm.test_mode & True) is False
    assert (tm.test_mode | True) is True
    assert (~tm.test_mode) is True
    tm.set_test_mode("on", verbose=False)
    assert int(tm.test_mode) == 1
    assert [10, 20][tm.test_mode] == 20
    assert (tm.test_mode & True) is True


def test_flag_hash_matches_bool():
    assert hash(tm.test_mode) == hash(False)
    assert {tm.test_mode: "x"}[False] == "x"


def test_skip_plots_only_in_full():
    tm.set_test_mode("on", verbose=False)
    assert tm.test_mode and not tm.skip_plots
    tm.set_test_mode("full", verbose=False)
    assert tm.test_mode and tm.skip_plots
    tm.set_test_mode("off", verbose=False)
    assert not tm.skip_plots


def test_skip_plots_env_is_independent():
    tm._reset_for_tests("off", skip_plots_env=True)
    assert tm.skip_plots
    assert not tm.test_mode


# ---------------------------------------------------------------------------
# set_test_mode
# ---------------------------------------------------------------------------


def test_set_test_mode_accepts_bools_and_returns_the_mode():
    assert tm.set_test_mode(True, verbose=False) == "on"
    assert tm.set_test_mode(False, verbose=False) == "off"
    assert tm.set_test_mode("FULL", verbose=False) == "full"
    assert tm.current_test_mode() == "full"


def test_set_test_mode_rejects_unknown_modes():
    with pytest.raises(ValueError, match="Unknown testing mode"):
        tm.set_test_mode("fast")
    assert tm.current_test_mode() == "off"


def test_set_test_mode_reports_the_switch(capsys):
    tm.set_test_mode("on")
    err = capsys.readouterr().err
    assert "Testing mode: on" in err


# ---------------------------------------------------------------------------
# Environment variable
# ---------------------------------------------------------------------------


def _import_helper(env, code):
    """Import the package in a subprocess with `env` set, and run `code`."""
    environment = dict(os.environ)
    environment.pop("TESTING_MODE", None)
    environment.pop("SKIP_PLOTS", None)
    environment.pop("TESTING_MODE_WIDGET", None)
    environment.update(env)
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    return result


@pytest.mark.parametrize(
    "value,expected_test,expected_skip",
    [
        ("off", "False", "False"),
        ("on", "True", "False"),
        ("full", "True", "True"),
    ],
)
def test_env_var_seeds_the_mode(value, expected_test, expected_skip):
    result = _import_helper(
        {"TESTING_MODE": value},
        "import jupytext_notebook_helper as h;"
        "print(h.current_test_mode(), h.test_mode, h.skip_plots)",
    )
    mode, test, skip = result.stdout.split()
    assert mode == value
    assert test == expected_test
    assert skip == expected_skip


def test_env_var_default_is_off():
    result = _import_helper(
        {},
        "import jupytext_notebook_helper as h; print(h.current_test_mode())",
    )
    assert result.stdout.strip() == "off"


def test_env_var_is_respected_but_not_a_lock():
    """TESTING_MODE wins by default; an explicit switch still works."""
    result = _import_helper(
        {"TESTING_MODE": "on"},
        "import jupytext_notebook_helper as h;"
        "print(h.test_mode);"
        "h.set_test_mode('off', verbose=False);"
        "print(h.test_mode)",
    )
    assert result.stdout.split() == ["True", "False"]


def test_invalid_env_var_falls_back_to_off_with_a_warning():
    result = _import_helper(
        {"TESTING_MODE": "yes-please"},
        "import jupytext_notebook_helper as h; print(h.current_test_mode())",
    )
    assert result.stdout.strip() == "off"
    assert "Ignoring TESTING_MODE" in result.stderr


def test_skip_plots_env_var_alone():
    result = _import_helper(
        {"SKIP_PLOTS": "1"},
        "import jupytext_notebook_helper as h; print(h.test_mode, h.skip_plots)",
    )
    assert result.stdout.split() == ["False", "True"]


def test_env_mode_is_reported():
    result = _import_helper(
        {"TESTING_MODE": "full"},
        "import jupytext_notebook_helper as h; print(h.env_test_mode())",
    )
    assert result.stdout.strip() == "full"


# ---------------------------------------------------------------------------
# Outside a notebook: no widget, no prompt, no blocking
# ---------------------------------------------------------------------------


def test_is_notebook_false_under_pytest():
    assert tm.is_notebook() is False


def test_select_test_mode_is_a_noop_outside_a_notebook(capsys, monkeypatch):
    """No widget, no input(), no output: scripts stay env-driven."""

    def _boom(*args, **kwargs):  # pragma: no cover - must never be called
        raise AssertionError("select_test_mode() must not read from stdin")

    monkeypatch.setattr("builtins.input", _boom)
    assert tm.select_test_mode() == "off"
    assert tm.select_test_mode(auto=True) == "off"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_import_in_script_mode_displays_nothing(capsys):
    """A plain `import` from a script prints nothing when the mode is off."""
    result = _import_helper({}, "import jupytext_notebook_helper  # noqa")
    assert result.stdout == ""
    assert "Testing mode" not in result.stderr


# ---------------------------------------------------------------------------
# In a notebook: widget, and fallback when ipywidgets is missing
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_notebook(monkeypatch):
    monkeypatch.setattr(tm, "is_notebook", lambda: True)


class _FakeWidget:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.observers = []

    def observe(self, handler, names=None):
        self.observers.append((handler, names))

    def fire(self, new):
        old, self.value = self.value, new
        for handler, _ in self.observers:
            handler({"name": "value", "old": old, "new": new})


class _FakeOutput:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def clear_output(self):
        pass


def _install_fake_ipywidgets(monkeypatch, displayed):
    widgets = types.ModuleType("ipywidgets")
    widgets.ToggleButtons = _FakeWidget
    widgets.HTML = lambda *a, **k: ("html", a, k)
    widgets.Output = _FakeOutput
    widgets.VBox = lambda children: children

    display_module = types.ModuleType("IPython.display")
    display_module.display = displayed.append

    monkeypatch.setitem(sys.modules, "ipywidgets", widgets)
    monkeypatch.setitem(sys.modules, "IPython.display", display_module)
    return widgets


def test_widget_switches_the_mode(monkeypatch, fake_notebook):
    displayed = []
    _install_fake_ipywidgets(monkeypatch, displayed)

    assert tm.select_test_mode() == "off"
    assert displayed, "the chooser must be displayed"
    toggle = displayed[0][0]
    assert [value for _label, value in toggle.options] == list(tm.SWITCHABLE_MODES)
    assert toggle.value == "off"

    toggle.fire("on")
    assert tm.current_test_mode() == "on"
    assert tm.test_mode  # the proxy follows, live


def test_widget_starts_on_the_current_mode(monkeypatch, fake_notebook):
    displayed = []
    _install_fake_ipywidgets(monkeypatch, displayed)
    tm.set_test_mode("on", verbose=False)
    tm.select_test_mode()
    assert displayed[0][0].value == "on"


def test_auto_chooser_is_silent_when_the_env_var_is_set(monkeypatch, fake_notebook):
    displayed = []
    _install_fake_ipywidgets(monkeypatch, displayed)
    tm._reset_for_tests("full", env_mode="full")
    tm.select_test_mode(auto=True)
    assert displayed == []
    # ... but an explicit call still offers the chooser.
    tm.select_test_mode()
    assert len(displayed) == 1


def test_auto_chooser_can_be_disabled(monkeypatch, fake_notebook):
    displayed = []
    _install_fake_ipywidgets(monkeypatch, displayed)
    monkeypatch.setenv("TESTING_MODE_WIDGET", "0")
    tm.select_test_mode(auto=True)
    assert displayed == []


@pytest.fixture
def without_ipywidgets(monkeypatch):
    """Make `import ipywidgets` fail, as on a machine that lacks it."""
    real_import = builtins.__import__

    def _no_ipywidgets(name, *args, **kwargs):
        if name == "ipywidgets":
            raise ImportError("No module named 'ipywidgets'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_ipywidgets)
    monkeypatch.delitem(sys.modules, "ipywidgets", raising=False)


def test_fallback_without_ipywidgets(capsys, fake_notebook, without_ipywidgets):
    """No ipywidgets: a one-line hint, no exception, mode unchanged."""
    assert tm.select_test_mode() == "off"
    err = capsys.readouterr().err
    assert "set_test_mode" in err
    assert len(err.strip().splitlines()) == 1
    assert tm.current_test_mode() == "off"
    # ... and the manual switch it points at works.
    assert tm.set_test_mode("on", verbose=False) == "on"
    assert tm.test_mode


def test_auto_fallback_without_ipywidgets_does_not_raise(
    capsys, fake_notebook, without_ipywidgets
):
    tm._auto_select()
    assert "set_test_mode" in capsys.readouterr().err


def test_auto_select_never_raises(monkeypatch, capsys, fake_notebook):
    monkeypatch.setattr(
        tm, "select_test_mode", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    tm._auto_select()  # must not propagate
    assert "boom" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Figure suppression is a start-up decision
# ---------------------------------------------------------------------------


def test_full_mode_in_a_notebook_warns_that_figures_do_not_change(
    capsys, fake_notebook
):
    tm.set_test_mode("full")
    err = capsys.readouterr().err
    assert "Figures stay" in err
    assert "matplotlib backend is fixed" in err
    # The mode itself did switch: only the figures stayed put.
    assert tm.current_test_mode() == "full"
    assert tm.test_mode


def test_full_mode_in_a_script_switches_the_backend(monkeypatch):
    used = []
    matplotlib = types.ModuleType("matplotlib")
    matplotlib.use = used.append
    monkeypatch.setitem(sys.modules, "matplotlib", matplotlib)

    tm.set_test_mode("on", verbose=False)
    assert used == []
    tm.set_test_mode("full", verbose=False)
    assert used == ["Agg"]


def test_switchable_modes_exclude_full():
    assert "full" not in tm.SWITCHABLE_MODES
    assert set(tm.SWITCHABLE_MODES) < set(tm.MODES)
