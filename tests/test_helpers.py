"""Unit tests for the runtime helpers."""

import jupytext_notebook_helper as h


def test_public_api():
    assert callable(h.print_header)
    assert callable(h.is_notebook)
    assert callable(h.set_test_mode)
    assert callable(h.select_test_mode)
    assert callable(h.current_test_mode)
    # `test_mode` / `skip_plots` are live proxies (read at use time), not bools,
    # but they behave like bools everywhere the notebooks use them.
    assert isinstance(bool(h.test_mode), bool)
    assert isinstance(bool(h.skip_plots), bool)


def test_star_import_surface():
    """`from jupytext_notebook_helper import *` exports exactly __all__."""
    namespace = {}
    exec("from jupytext_notebook_helper import *", namespace)  # noqa: S102
    exported = {k for k in namespace if not k.startswith("__")}
    assert exported == set(h.__all__)


def test_print_header(capsys):
    h.print_header("Hello")
    out = capsys.readouterr().out
    assert "Hello" in out
    assert "=" * 10 in out


def test_is_notebook_false_under_pytest():
    assert h.is_notebook() is False
