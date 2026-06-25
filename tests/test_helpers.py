"""Unit tests for the runtime helpers."""

import jupytext_notebook_helper as h


def test_public_api():
    assert callable(h.print_header)
    assert callable(h.is_notebook)
    assert isinstance(h.test_mode, bool)
    assert isinstance(h.skip_plots, bool)


def test_print_header(capsys):
    h.print_header("Hello")
    out = capsys.readouterr().out
    assert "Hello" in out
    assert "=" * 10 in out


def test_is_notebook_false_under_pytest():
    assert h.is_notebook() is False
