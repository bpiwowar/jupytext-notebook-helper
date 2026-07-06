"""Integration tests for the notebook filter (run via the CLI)."""

import json
import subprocess
import sys
import textwrap

SAMPLE = textwrap.dedent(
    """
    # %% [markdown]
    # # Sample notebook

    # %% tags=["teacher"]
    secret = "teacher-only"

    # %%
    # [[student]] implement the answer
    # >x = 0
    answer = 42
    # [[/student]]
    """
).lstrip()


def _run(args, src_path):
    proc = subprocess.run(
        [sys.executable, "-m", "jupytext_notebook_helper.filter", *args, str(src_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def _cell_source(cell):
    """nbformat stores source as a str or a list of lines; normalise to str."""
    src = cell["source"]
    return src if isinstance(src, str) else "".join(src)


def _text(nb):
    return "\n".join(_cell_source(c) for c in nb["cells"])


def _write_module(tmp_path, dotted, src):
    path = tmp_path / "src" / (dotted.replace(".", "/") + ".py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(src))
    return path


def test_student_blanks_solution_and_drops_teacher(tmp_path):
    src = tmp_path / "sample.py"
    src.write_text(SAMPLE)
    text = _text(_run(["--exclude", "teacher"], src))
    assert "Not implemented yet" in text  # solution replaced by an assertion
    assert "answer = 42" not in text  # solution body removed
    assert "x = 0" in text  # `# >` hint uncommented
    assert "teacher-only" not in text  # teacher-tagged cell dropped


def test_teacher_keeps_solution_and_teacher_cell(tmp_path):
    src = tmp_path / "sample.py"
    src.write_text(SAMPLE)
    text = _text(_run(["--teacher"], src))
    assert "answer = 42" in text  # full solution kept
    assert "teacher-only" in text  # teacher-tagged cell kept
    assert "Not implemented yet" not in text


# --------------------------------------------------------------------------- #
# Automatic import gathering + internal inlining
# --------------------------------------------------------------------------- #

IMPORTS_NB = textwrap.dedent(
    """
    # %%
    # [[imports]]

    # %%
    import numpy as np
    x = np.zeros(3)

    # %%
    from collections import defaultdict
    d = defaultdict(int)
    """
).lstrip()


def test_imports_gathered_into_marker(tmp_path):
    src = tmp_path / "nb.py"
    src.write_text(IMPORTS_NB)
    nb = _run([], src)
    cells = [_cell_source(c) for c in nb["cells"]]
    marker_cell = cells[0]
    # Both imports collected into the marker cell...
    assert "import numpy as np" in marker_cell
    assert "from collections import defaultdict" in marker_cell
    # ...and removed from the cells they came from (only the usage remains).
    body = "\n".join(cells[1:])
    assert "x = np.zeros(3)" in body
    assert "d = defaultdict(int)" in body
    assert "import numpy" not in body
    assert "import defaultdict" not in body


INTERNAL_NB = textwrap.dedent(
    """
    # %%
    # [[imports]]

    # %%
    from lib import used
    result = used()
    """
).lstrip()


def test_internal_import_inlined_with_transitive_deps(tmp_path):
    _write_module(
        tmp_path,
        "lib",
        """
        import numpy as np

        CONST = 3

        def _scale(x):
            return x * CONST

        def used():
            return _scale(np.zeros(CONST))

        def unused():
            raise RuntimeError("should never be inlined")
        """,
    )
    src = tmp_path / "nb.py"
    src.write_text(INTERNAL_NB)
    nb = _run(["--src-root", str(tmp_path / "src")], src)
    text = _text(nb)

    # requested symbol + transitive deps are inlined
    assert "def used(" in text
    assert "def _scale(" in text
    assert "CONST = 3" in text
    # unused / side-effectful code is left behind
    assert "def unused(" not in text
    assert "should never be inlined" not in text
    # the internal module's external dependency is surfaced to the imports cell
    assert "import numpy as np" in _cell_source(nb["cells"][0])
    # the from-import statement itself is gone (replaced by the code)
    assert "from lib import used" not in text
    assert "result = used()" in text


def test_imports_inserted_before_first_code_cell_without_marker(tmp_path):
    src = tmp_path / "nb.py"
    src.write_text(
        textwrap.dedent(
            """
            # %% [markdown]
            # # Title

            # %%
            import numpy as np
            x = np.zeros(3)
            """
        ).lstrip()
    )
    nb = _run([], src)
    types = [c["cell_type"] for c in nb["cells"]]
    # markdown title, then the inserted imports cell, then the (import-stripped) body
    assert types[0] == "markdown"
    assert types[1] == "code"
    assert "import numpy as np" in _cell_source(nb["cells"][1])
    body = _text(nb)
    assert "x = np.zeros(3)" in body
    # the import was moved out of its original cell
    assert _cell_source(nb["cells"][2]).count("import numpy") == 0


def test_star_import_of_internal_module(tmp_path):
    _write_module(
        tmp_path,
        "lib",
        """
        def a():
            return _shared()

        def b():
            return 2

        def _shared():
            return 1
        """,
    )
    src = tmp_path / "nb.py"
    src.write_text(
        textwrap.dedent(
            """
            # %%
            # [[imports]]

            # %%
            from lib import *
            v = a() + b()
            """
        ).lstrip()
    )
    nb = _run(["--src-root", str(tmp_path / "src")], src)
    text = _text(nb)
    assert "def a(" in text and "def b(" in text and "def _shared(" in text
    assert "from lib import *" not in text


def test_pip_cell_covers_late_and_inlined_imports(tmp_path):
    """The pip cell is rendered after import gathering: it must cover imports
    located *after* it, including those pulled in by inlined internal modules."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'sample'\n")
    (tmp_path / "uv.lock").write_text(
        textwrap.dedent(
            """
            version = 1

            [[package]]
            name = "sample"
            version = "0.1.0"

            [package.metadata]
            requires-dist = [{ name = "numpy" }, { name = "torch" }]

            [[package]]
            name = "numpy"
            version = "2.0.0"

            [[package]]
            name = "torch"
            version = "2.8.0"
            """
        )
    )
    _write_module(
        tmp_path,
        "mylib",
        """
        import torch

        def f(x):
            return torch.relu(x)
        """,
    )
    src = tmp_path / "sample.py"
    src.write_text(
        textwrap.dedent(
            """
            # %% tags=["pip"]

            # %%
            # [[imports]]

            # %%
            import numpy as np

            x = np.zeros(3)

            # %%
            from mylib import f
            """
        ).lstrip()
    )
    nb = _run(
        [
            "--uv-root",
            str(tmp_path),
            "--src-root",
            str(tmp_path / "src"),
        ],
        src,
    )
    pip_source = next(
        _cell_source(c) for c in nb["cells"] if "%pip install" in _cell_source(c)
    )
    # `numpy` is imported after the pip cell, `torch` only by the inlined module
    assert "numpy==2.0.0" in pip_source
    assert "torch==2.8.0" in pip_source
