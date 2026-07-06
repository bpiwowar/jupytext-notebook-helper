"""Tests for the resolved-import execution / testing mode."""

import textwrap
import traceback

import pytest

from jupytext_notebook_helper.run import run_notebook


def _write_module(tmp_path, dotted, src):
    path = tmp_path / "src" / (dotted.replace(".", "/") + ".py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(src))
    return path


def _write_nb(tmp_path, src):
    path = tmp_path / "nb.py"
    path.write_text(textwrap.dedent(src).lstrip())
    return path


def test_run_inlines_and_executes(tmp_path):
    _write_module(
        tmp_path,
        "lib",
        """
        import math

        FACTOR = 2

        def _double(x):
            return x * FACTOR

        def area(r):
            return _double(math.pi) * r
        """,
    )
    nb = _write_nb(
        tmp_path,
        """
        # %%
        from lib import area
        result = area(10)
        """,
    )
    ns = run_notebook(str(nb), src_root=str(tmp_path / "src"))
    assert ns["result"] == pytest.approx(2 * 3.141592653589793 * 10)


def test_run_does_not_execute_module_side_effects(tmp_path):
    marker = tmp_path / "ran.txt"
    _write_module(
        tmp_path,
        "lib",
        f"""
        from pathlib import Path

        Path({str(marker)!r}).write_text("side effect ran")

        def wanted():
            return 1
        """,
    )
    nb = _write_nb(
        tmp_path,
        """
        # %%
        from lib import wanted
        value = wanted()
        """,
    )
    ns = run_notebook(str(nb), src_root=str(tmp_path / "src"))
    assert ns["value"] == 1
    # The top-level side effect is not part of `wanted`, so it must not run.
    assert not marker.exists()


def test_run_traceback_points_at_library_source(tmp_path):
    lib = _write_module(
        tmp_path,
        "lib",
        """
        def boom():
            raise ValueError("kaboom")
        """,
    )
    nb = _write_nb(
        tmp_path,
        """
        # %%
        from lib import boom
        boom()
        """,
    )
    with pytest.raises(ValueError) as exc_info:
        run_notebook(str(nb), src_root=str(tmp_path / "src"))

    frames = traceback.extract_tb(exc_info.value.__traceback__)
    # A frame must point at the real library file, on the `raise` line (line 3
    # of the dedented source: blank, `def boom`, `raise`).
    lib_frames = [f for f in frames if f.filename == str(lib)]
    assert lib_frames, f"no frame in {lib}: {[f.filename for f in frames]}"
    assert lib_frames[-1].lineno == 3
    assert "raise ValueError" in (lib_frames[-1].line or "")


def test_run_traceback_points_at_notebook_cell(tmp_path):
    nb = _write_nb(
        tmp_path,
        """
        # %% [markdown]
        # # A notebook

        # %%
        x = 1

        # %%
        y = x + 1
        raise RuntimeError("in notebook")
        """,
    )
    with pytest.raises(RuntimeError) as exc_info:
        run_notebook(str(nb), src_root=str(tmp_path / "src"))

    frames = traceback.extract_tb(exc_info.value.__traceback__)
    nb_frames = [f for f in frames if f.filename == str(nb)]
    assert nb_frames, f"no notebook frame: {[f.filename for f in frames]}"
    # The `raise` is on line 9 of the notebook file.
    assert nb_frames[-1].lineno == 9
    assert "in notebook" in (nb_frames[-1].line or "")


def test_run_ignores_magics(tmp_path):
    nb = _write_nb(
        tmp_path,
        """
        # %%
        %matplotlib inline
        !echo hello
        z = 41 + 1
        """,
    )
    ns = run_notebook(str(nb), src_root=str(tmp_path / "src"))
    assert ns["z"] == 42


def test_run_nested_internal_modules(tmp_path):
    _write_module(
        tmp_path,
        "top",
        """
        from base import core

        def feature(x):
            return core(x) + 1
        """,
    )
    _write_module(
        tmp_path,
        "base",
        """
        BASE = 10

        def core(x):
            return x * BASE
        """,
    )
    nb = _write_nb(
        tmp_path,
        """
        # %%
        from top import feature
        out = feature(3)
        """,
    )
    ns = run_notebook(str(nb), src_root=str(tmp_path / "src"))
    assert ns["out"] == 31
