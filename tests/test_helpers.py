"""Unit tests for the runtime helpers."""

import jupytext_notebook_helper as h


def test_public_api():
    assert callable(h.print_header)
    assert h.OutputMode is not None


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


def test_importing_this_package_tells_hardware_about_figures():
    """The profile note gains an `images:` part, which is this side's to say."""
    import cs_lab.machine as machine

    assert h._figure_state in machine._state_notes
    assert h._figure_state().startswith("images: ")
