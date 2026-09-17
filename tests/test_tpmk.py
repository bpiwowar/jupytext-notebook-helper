"""Integration tests for the shared make rules (jupytext_notebook_helper/tp.mk).

A throw-away course is built in a tmp directory (two sources, no internal
`src/` modules, no uv) and driven with real `make`, so the pattern rules,
the output layout and `clean` are exercised the way a course exercises them.

`PYTHON` is set to the empty string and a `python` shim pointing at the
current interpreter is put first on `PATH`: the rules build their commands as
`$(PYTHON) python -m jupytext_notebook_helper.filter ...`, so this runs the
filter in-place without needing `uv`.
"""

import os
import shutil
import subprocess
import sys
import textwrap
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TP_MK = os.path.join(ROOT, "jupytext_notebook_helper", "tp.mk")

SOURCE = textwrap.dedent(
    """
    # %% [markdown]
    # # {title}

    # %%
    import numpy as np

    # %% tags=["teacher"]
    secret = "teacher-only"

    # %%
    # [[student]] compute the answer
    answer = np.int64(42)
    # [[/student]]
    """
).lstrip()

UV_LOCK = textwrap.dedent(
    """
    version = 1
    requires-python = ">=3.10"

    [[package]]
    name = "course"
    version = "0"
    source = { editable = "." }

    [package.metadata]
    requires-dist = [{ name = "numpy" }]

    [[package]]
    name = "numpy"
    version = "2.0.0"
    source = { registry = "https://pypi.org/simple" }
    """
).lstrip()

MAKEFILE = textwrap.dedent(
    """
    DESTDIR_TP := student
    ROOT       := .
    ZIP        ?= dist/tp.zip
    PYTHON     :=
    include {tp_mk}
    """
).lstrip()

pytestmark = pytest.mark.skipif(
    shutil.which("make") is None, reason="make is not available"
)


def _age(path, seconds=60):
    """Backdate a file: make on macOS compares mtimes with a 1s resolution, so
    a source written in the same second as its output looks 'not newer'."""
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


def _course(tmp_path, names=("tp1", "tp2"), makefile_extra="", makefile_head=""):
    """Create a minimal course directory and return its path."""
    (tmp_path / "sources").mkdir()
    for name in names:
        source = tmp_path / "sources" / f"{name}.py"
        source.write_text(SOURCE.format(title=name))
        _age(source)
    (tmp_path / "sources" / "STUDENT_README.md").write_text("# TP\n")
    # $(STUDENT_ENV_DIR)/pyproject.toml depends on $(ROOT)/pyproject.toml, and
    # the Colab install cell reads the pinned versions from $(ROOT)/uv.lock.
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "course"\nversion = "0"\ndependencies = ["numpy"]\n'
    )
    (tmp_path / "uv.lock").write_text(UV_LOCK)
    # makefile_head goes before the include, as a course's settings do.
    (tmp_path / "Makefile").write_text(
        makefile_head + MAKEFILE.format(tp_mk=TP_MK) + makefile_extra
    )
    return tmp_path


def _make(cwd, *targets):
    bin_dir = cwd / ".shim"
    bin_dir.mkdir(exist_ok=True)
    shim = bin_dir / "python"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    shim.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        ["make", *targets],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"make {' '.join(targets)} failed:\n{proc.stdout}\n{proc.stderr}"
        )
    return proc


# --------------------------------------------------------------------------
# output layout
# --------------------------------------------------------------------------


def test_teacher_puts_colab_variants_in_a_subdirectory(tmp_path):
    course = _course(tmp_path)
    _make(course, "teacher")

    for name in ("tp1", "tp2"):
        assert (course / "teacher" / f"{name}.ipynb").is_file()
        assert (course / "teacher" / "colab" / f"{name}.ipynb").is_file()
        # the old flat name is gone
        assert not (course / "teacher" / f"{name}.colab.ipynb").exists()

    # nothing but the local notebooks and the colab/ directory at the top level
    assert sorted(p.name for p in (course / "teacher").iterdir()) == [
        "colab",
        "tp1.ipynb",
        "tp2.ipynb",
    ]


def test_solution_puts_colab_variants_in_a_subdirectory(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    _make(course, "solution")

    assert (course / "solution" / "tp1.ipynb").is_file()
    assert (course / "solution" / "colab" / "tp1.ipynb").is_file()
    assert not (course / "solution" / "tp1.colab.ipynb").exists()


def test_student_notebooks_and_bundle_layout(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    # `student` also builds the uv bundle, which needs `uv lock`; build only the
    # notebook targets so the test stays offline.
    _make(course, "student/tp1.ipynb", "student/colab/tp1.ipynb")

    assert (course / "student" / "tp1.ipynb").is_file()
    assert (course / "student" / "colab" / "tp1.ipynb").is_file()
    assert not (course / "student" / "tp1.colab.ipynb").exists()


def test_colab_subdirectory_is_configurable(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    _make(course, "COLAB_SUBDIR=gcolab", "teacher")

    assert (course / "teacher" / "gcolab" / "tp1.ipynb").is_file()
    assert not (course / "teacher" / "colab").exists()


def test_empty_colab_subdirectory_is_rejected(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    with pytest.raises(AssertionError, match="COLAB_SUBDIR must not be empty"):
        _make(course, "COLAB_SUBDIR=", "teacher")


# --------------------------------------------------------------------------
# the right filter flags reach the right file
# --------------------------------------------------------------------------


def _text(path):
    return path.read_text()


def test_colab_variant_gets_the_install_cell_and_the_local_one_does_not(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    _make(course, "teacher")

    colab = _text(course / "teacher" / "colab" / "tp1.ipynb")
    local = _text(course / "teacher" / "tp1.ipynb")
    assert "%pip install" in colab
    assert "%pip install" not in local
    # both are teacher variants: the teacher-tagged cell survives
    assert "teacher-only" in colab
    assert "teacher-only" in local


def test_student_colab_has_no_solution(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    _make(course, "student/colab/tp1.ipynb")

    colab = _text(course / "student" / "colab" / "tp1.ipynb")
    assert "%pip install" in colab
    assert "teacher-only" not in colab
    assert "Not implemented yet" in colab


# --------------------------------------------------------------------------
# incremental rebuilds and per-name targets
# --------------------------------------------------------------------------


def test_second_build_is_a_no_op(tmp_path):
    course = _course(tmp_path)
    _make(course, "teacher")
    out = _make(course, "teacher").stdout
    assert "Nothing to be done" in out or "up to date" in out


def test_touching_a_source_rebuilds_only_its_variants(tmp_path):
    course = _course(tmp_path)
    _make(course, "teacher")
    stamps = {p: p.stat().st_mtime_ns for p in (course / "teacher").rglob("*.ipynb")}

    src = course / "sources" / "tp1.py"
    src.write_text(src.read_text() + "\n# %%\nprint('again')\n")
    # ... and land it in a strictly later second than the outputs just built
    _age(src, -2)
    _make(course, "teacher")

    rebuilt = {
        str(path.relative_to(course))
        for path, before in stamps.items()
        if path.stat().st_mtime_ns != before
    }
    # both tp1 variants, and only those
    assert rebuilt == {"teacher/tp1.ipynb", "teacher/colab/tp1.ipynb"}


# --------------------------------------------------------------------------
# clean
# --------------------------------------------------------------------------


def test_clean_removes_the_colab_subdirectories(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    _make(course, "teacher", "solution", "student/tp1.ipynb", "student/colab/tp1.ipynb")
    _make(course, "clean")

    assert not (course / "teacher").exists()
    assert not (course / "solution").exists()
    assert not (course / "student" / "colab").exists()
    assert not (course / "student" / "tp1.ipynb").exists()


def test_clean_removes_legacy_flat_colab_notebooks(tmp_path):
    """An upgraded checkout still has the pre-0.8 <name>.colab.ipynb on disk."""
    course = _course(tmp_path, names=("tp1",))
    for d in ("student", "teacher", "solution"):
        (course / d).mkdir(exist_ok=True)
        (course / d / "tp1.colab.ipynb").write_text("{}")

    _make(course, "clean")

    for d in ("student", "teacher", "solution"):
        assert not (course / d / "tp1.colab.ipynb").exists()


# --------------------------------------------------------------------------
# help / introspection
# --------------------------------------------------------------------------


def test_help_documents_the_new_layout(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    out = _make(course, "help").stdout
    assert "student/colab/<name>.ipynb" in out
    assert "teacher/colab/<name>.ipynb" in out


# --------------------------------------------------------------------------
# solution bundle, release switch
# --------------------------------------------------------------------------

# Solutions under the deployed directory, and a bundle env taken straight from
# the course root so that no `uv lock` runs.
SOLUTION_MAKEFILE = textwrap.dedent(
    """
    SOLUTION_DIR     := student/solution
    ZIP              := student/tp.zip
    SOLUTION_ZIP     := student/tp-solution.zip
    BUNDLE_PYPROJECT := pyproject.toml
    BUNDLE_LOCK      := uv.lock
    """
)


@pytest.mark.skipif(shutil.which("zip") is None, reason="zip is not available")
def test_solution_bundle_ships_the_solution_notebooks(tmp_path):
    import zipfile

    course = _course(tmp_path, names=("tp1",), makefile_head=SOLUTION_MAKEFILE)
    _make(course, "bundle")

    with zipfile.ZipFile(course / "student" / "tp.zip") as student:
        student_nb = student.read("notebooks/tp1.ipynb").decode()
    with zipfile.ZipFile(course / "student" / "tp-solution.zip") as solution:
        names = set(solution.namelist())
        solution_nb = solution.read("notebooks/tp1.ipynb").decode()

    assert {"pyproject.toml", "uv.lock", "README.md"} <= names
    assert "np.int64(42)" not in student_nb
    assert "np.int64(42)" in solution_nb
    assert "teacher-only" not in solution_nb


def _rsync_line(course, *overrides):
    out = _make(course, "-n", "rsync", "SSH_HOST=h", "SSH_PATH=/p", *overrides)
    (line,) = [l for l in out.stdout.splitlines() if l.startswith("rsync ")]
    return line


def test_rsync_keeps_the_solutions_back_until_published(tmp_path):
    course = _course(tmp_path, names=("tp1",), makefile_head=SOLUTION_MAKEFILE)

    held = _rsync_line(course)
    assert '--exclude "/solution/"' in held
    assert '--exclude "/tp-solution.zip"' in held
    # before any include, since rsync stops at the first match
    assert held.index("--exclude") < held.index("--include")

    released = _rsync_line(course, "PUBLISH_SOLUTIONS=yes")
    assert '--include "/solution/**"' in released
    assert '--include "/tp-solution.zip"' in released
    assert '--exclude "/solution/"' not in released


def test_manifest_lists_the_solutions_only_once_published(tmp_path):
    import json

    course = _course(tmp_path, names=("tp1",), makefile_head=SOLUTION_MAKEFILE)

    _make(course, "manifest", "MANIFEST=held.json")
    held = json.loads((course / "held.json").read_text())
    assert held["bundles"] == [{"id": "student", "path": "tp.zip"}]
    assert not any(f.get("solution") for f in held["practicals"][0]["files"])

    _make(
        course,
        "manifest",
        "MANIFEST=released.json",
        "PUBLISH_SOLUTIONS=yes",
        "MANIFEST_SOLUTION_LABEL=Corrigé, local",
    )
    released = json.loads((course / "released.json").read_text())
    assert released["bundles"][1] == {"id": "solution", "path": "tp-solution.zip"}
    assert {
        "label": "Corrigé, local",
        "path": "solution/tp1.ipynb",
        "solution": True,
    } in released["practicals"][0]["files"]
