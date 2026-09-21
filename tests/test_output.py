"""Tests for the output axis: where a source's figures and logs go."""

import pytest

from jupytext_notebook_helper import output as output_module
from jupytext_notebook_helper.output import (
    ENV_OUTPUT,
    OutputMode,
    current_output_mode,
    set_output_mode,
)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv(ENV_OUTPUT, raising=False)
    output_module._reset_for_tests()
    yield
    output_module._reset_for_tests()


# ---------------------------------------------------------------------------
# Output mode
# ---------------------------------------------------------------------------


def test_output_defaults_to_console_outside_a_notebook():
    assert current_output_mode() is OutputMode.CONSOLE


@pytest.mark.parametrize(
    "written,expected",
    [
        ("off", OutputMode.OFF),
        ("OFF", OutputMode.OFF),
        ("notebook", OutputMode.NOTEBOOK),
        ("console", OutputMode.CONSOLE),
    ],
)
def test_output_reads_the_environment(monkeypatch, written, expected):
    monkeypatch.setenv(ENV_OUTPUT, written)
    assert current_output_mode() is expected


def test_an_unparseable_output_mode_warns_and_is_ignored(monkeypatch, caplog):
    monkeypatch.setenv(ENV_OUTPUT, "sideways")
    assert current_output_mode() is OutputMode.CONSOLE
    assert "sideways" in caplog.text


def test_set_output_mode_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv(ENV_OUTPUT, "off")
    set_output_mode("console")
    assert current_output_mode() is OutputMode.CONSOLE


def test_set_output_mode_rejects_nonsense():
    with pytest.raises(ValueError, match="unknown output mode"):
        set_output_mode("sideways")


def test_changing_figure_output_after_set_up_warns():
    """matplotlib's backend is fixed at start-up; say so rather than lie."""
    output_module.mark_applied(OutputMode.OFF)
    with pytest.warns(RuntimeWarning, match="needs a restart"):
        set_output_mode(OutputMode.CONSOLE)


def test_switching_between_two_showing_modes_is_silent():
    output_module.mark_applied(OutputMode.CONSOLE)
    set_output_mode(OutputMode.NOTEBOOK)  # no warning: both draw figures
