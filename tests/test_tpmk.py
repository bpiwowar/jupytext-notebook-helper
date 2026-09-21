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


def _make(cwd, *targets, check=True):
    bin_dir = cwd / ".shim"
    bin_dir.mkdir(exist_ok=True)
    shim = bin_dir / "python"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    shim.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    # `publish-git` commits: give git an identity of its own rather than the
    # machine's, which a CI runner does not have.
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "tp.mk tests"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "tests@example.invalid"
    proc = subprocess.run(
        ["make", *targets],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            f"make {' '.join(targets)} failed:\n{proc.stdout}\n{proc.stderr}"
        )
    return proc


# --------------------------------------------------------------------------
# output layout
# --------------------------------------------------------------------------


def test_teacher_puts_each_variant_in_its_own_subdirectory(tmp_path):
    course = _course(tmp_path)
    _make(course, "teacher")

    for name in ("tp1", "tp2"):
        assert (course / "teacher" / "local" / f"{name}.ipynb").is_file()
        assert (course / "teacher" / "colab" / f"{name}.ipynb").is_file()

    # nothing but the two variant directories at the top level
    assert sorted(p.name for p in (course / "teacher").iterdir()) == [
        "colab",
        "local",
    ]


def test_solution_puts_each_variant_in_its_own_subdirectory(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    _make(course, "solution", "PUBLISH_SOLUTIONS=yes")

    assert (course / "solution" / "local" / "tp1.ipynb").is_file()
    assert (course / "solution" / "colab" / "tp1.ipynb").is_file()
    assert sorted(p.name for p in (course / "solution").iterdir()) == [
        "colab",
        "local",
    ]


def test_student_notebooks_and_bundle_layout(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    # `student` also builds the uv bundle, which needs `uv lock`; build only the
    # notebook targets so the test stays offline.
    _make(course, "student/local/tp1.ipynb", "student/colab/tp1.ipynb")

    assert (course / "student" / "local" / "tp1.ipynb").is_file()
    assert (course / "student" / "colab" / "tp1.ipynb").is_file()
    assert not (course / "student" / "tp1.ipynb").exists()


def test_colab_subdirectory_is_configurable(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    _make(course, "COLAB_SUBDIR=gcolab", "teacher")

    assert (course / "teacher" / "gcolab" / "tp1.ipynb").is_file()
    assert not (course / "teacher" / "colab").exists()


def test_local_subdirectory_is_configurable(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    _make(course, "LOCAL_SUBDIR=uv", "teacher")

    assert (course / "teacher" / "uv" / "tp1.ipynb").is_file()
    assert not (course / "teacher" / "local").exists()


@pytest.mark.parametrize(
    "override,message",
    [
        ("COLAB_SUBDIR=", "COLAB_SUBDIR must not be empty"),
        ("LOCAL_SUBDIR=", "LOCAL_SUBDIR must not be empty"),
        ("LOCAL_SUBDIR=colab", "LOCAL_SUBDIR and COLAB_SUBDIR must differ"),
    ],
)
def test_bad_variant_subdirectories_are_rejected(tmp_path, override, message):
    course = _course(tmp_path, names=("tp1",))
    with pytest.raises(AssertionError, match=message):
        _make(course, override, "teacher")


# --------------------------------------------------------------------------
# the right filter flags reach the right file
# --------------------------------------------------------------------------


def _text(path):
    return path.read_text()


def test_colab_variant_gets_the_install_cell_and_the_local_one_does_not(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    _make(course, "teacher")

    colab = _text(course / "teacher" / "colab" / "tp1.ipynb")
    local = _text(course / "teacher" / "local" / "tp1.ipynb")
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
    assert rebuilt == {"teacher/local/tp1.ipynb", "teacher/colab/tp1.ipynb"}


def test_editing_an_inlined_module_rebuilds_every_variant(tmp_path):
    """The depfile names the course's own paths, solutions under student/ too."""
    course = _course(
        tmp_path, names=("tp1",), makefile_head="SOLUTION_DIR := student/solution\n"
    )
    (course / "src").mkdir(exist_ok=True)
    (course / "src" / "helper.py").write_text("VALUE = 1\n")
    src = course / "sources" / "tp1.py"
    src.write_text(src.read_text() + "\n# %%\nfrom helper import VALUE\nprint(VALUE)\n")
    _make(course, "teacher", "solution", "PUBLISH_SOLUTIONS=yes")

    depfile = (course / ".deps" / "tp1.d").read_text()
    for path in (
        "teacher/local/",
        "student/solution/local/",
        "student/solution/colab/",
    ):
        assert f"{path}tp1.ipynb" in depfile.split(":", 1)[0]

    before = (
        (course / "student" / "solution" / "local" / "tp1.ipynb").stat().st_mtime_ns
    )
    helper = course / "src" / "helper.py"
    helper.write_text("VALUE = 2\n")
    _age(helper, -2)
    _make(course, "teacher", "solution", "PUBLISH_SOLUTIONS=yes")
    after = (course / "student" / "solution" / "local" / "tp1.ipynb").stat().st_mtime_ns
    assert after != before


# --------------------------------------------------------------------------
# clean
# --------------------------------------------------------------------------


def test_clean_removes_the_colab_subdirectories(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    _make(
        course,
        "teacher",
        "solution",
        "student/local/tp1.ipynb",
        "student/colab/tp1.ipynb",
    )
    _make(course, "clean")

    assert not (course / "teacher").exists()
    assert not (course / "solution").exists()
    assert not (course / "student" / "colab").exists()
    assert not (course / "student" / "local").exists()


def test_clean_removes_notebooks_at_their_old_paths(tmp_path):
    """An upgraded checkout still has <name>.colab.ipynb (before 0.8) and
    <name>.ipynb at the root of an output directory (before 2.0) on disk."""
    course = _course(tmp_path, names=("tp1",))
    for d in ("student", "teacher", "solution"):
        (course / d).mkdir(exist_ok=True)
        (course / d / "tp1.colab.ipynb").write_text("{}")
        (course / d / "tp1.ipynb").write_text("{}")
    (course / "student" / "notes.ipynb").write_text("{}")

    _make(course, "clean")

    for d in ("student", "teacher", "solution"):
        assert not (course / d / "tp1.colab.ipynb").exists()
        assert not (course / d / "tp1.ipynb").exists()
    # the student directory is cleaned file by file: what the build did not
    # write stays
    assert (course / "student" / "notes.ipynb").exists()


# --------------------------------------------------------------------------
# help / introspection
# --------------------------------------------------------------------------


def test_help_documents_the_new_layout(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    out = _make(course, "help").stdout
    assert "local/<name>.ipynb" in out
    assert "colab/<name>.ipynb" in out


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
    _make(course, "bundle", "PUBLISH_SOLUTIONS=yes")

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
    (line,) = [ln for ln in out.stdout.splitlines() if ln.startswith("rsync ")]
    return line


def test_rsync_keeps_the_solutions_back_until_published(tmp_path):
    course = _course(tmp_path, names=("tp1",), makefile_head=SOLUTION_MAKEFILE)

    held = _rsync_line(course)
    assert '--exclude "/solution/"' in held
    assert '--exclude "/tp-solution.zip"' in held
    # before any include, since rsync stops at the first match
    assert held.index("--exclude") < held.index("--include")

    # both variant directories, or rsync never descends into them
    assert '--include "local/"' in held
    assert '--include "colab/"' in held

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
        "path": "solution/local/tp1.ipynb",
        "solution": True,
    } in released["practicals"][0]["files"]


# --------------------------------------------------------------------------
# what is handed out: the sources' own `publish:` / `solution:` headers
# --------------------------------------------------------------------------


def _with_header(course, name, **keys):
    """Give a source a percent header carrying those metadata keys."""
    source = course / "sources" / f"{name}.py"
    header = "".join(f"#     {key}: {value}\n" for key, value in keys.items())
    source.write_text(
        "# ---\n# jupyter:\n#   metadata:\n" + header + "# ---\n\n" + source.read_text()
    )
    _age(source)


def test_an_unpublished_source_reaches_no_student_but_is_still_built(tmp_path):
    course = _course(tmp_path, names=("tp1", "tp2"))
    _with_header(course, "tp2", publish="no")

    _make(course, "student/local/tp1.ipynb", "teacher")
    _make(course, "student", "ZIP=")

    assert (course / "student" / "local" / "tp1.ipynb").is_file()
    assert not (course / "student" / "local" / "tp2.ipynb").exists()
    assert not (course / "student" / "colab" / "tp2.ipynb").exists()
    # held back from the students, not from the teacher — nor from `check`
    assert (course / "teacher" / "local" / "tp2.ipynb").is_file()


def test_holding_a_source_back_removes_the_notebook_it_already_built(tmp_path):
    course = _course(tmp_path, names=("tp1", "tp2"))
    _make(course, "student", "ZIP=")
    assert (course / "student" / "local" / "tp2.ipynb").is_file()

    _with_header(course, "tp2", publish="no")
    _make(course, "student", "ZIP=")
    assert not (course / "student" / "local" / "tp2.ipynb").exists()
    assert not (course / "student" / "colab" / "tp2.ipynb").exists()


def test_a_header_releases_one_corrige_early(tmp_path):
    course = _course(tmp_path, names=("tp1", "tp2"), makefile_head=SOLUTION_MAKEFILE)
    _with_header(course, "tp1", solution="yes")

    # PUBLISH_SOLUTIONS is still `no`: it is only what a silent header means.
    _make(course, "solution", "SOLUTION_ZIP=")
    assert (course / "student" / "solution" / "local" / "tp1.ipynb").is_file()
    assert not (course / "student" / "solution" / "local" / "tp2.ipynb").exists()

    line = _rsync_line(course)
    assert '--include "/solution/**"' in line


def test_a_header_holds_one_corrige_back_when_the_course_releases_them(tmp_path):
    course = _course(tmp_path, names=("tp1", "tp2"), makefile_head=SOLUTION_MAKEFILE)
    _with_header(course, "tp2", solution="no")

    _make(course, "solution", "SOLUTION_ZIP=", "PUBLISH_SOLUTIONS=yes")
    assert (course / "student" / "solution" / "local" / "tp1.ipynb").is_file()
    assert not (course / "student" / "solution" / "local" / "tp2.ipynb").exists()


def test_the_manifest_follows_the_headers(tmp_path):
    import json

    course = _course(tmp_path, names=("tp1", "tp2"), makefile_head=SOLUTION_MAKEFILE)
    _with_header(course, "tp1", solution="yes")
    _with_header(course, "tp2", publish="no")

    _make(course, "manifest", "MANIFEST=m.json")
    listed = json.loads((course / "m.json").read_text())
    assert [entry["id"] for entry in listed["practicals"]] == ["tp1"]
    assert any(f.get("solution") for f in listed["practicals"][0]["files"])


def test_show_selection_says_what_goes_out(tmp_path):
    course = _course(tmp_path, names=("tp1", "tp2"))
    _with_header(course, "tp2", publish="no")

    out = _make(course, "show-selection").stdout
    assert "tp1" in out and "published" in out
    assert "held back" in out


# --------------------------------------------------------------------------
# index.html
# --------------------------------------------------------------------------

BUNDLE_MAKEFILE = textwrap.dedent(
    """
    ZIP              := student/tp.zip
    BUNDLE_PYPROJECT := pyproject.toml
    BUNDLE_LOCK      := uv.lock
    """
)

INDEX_MAKEFILE = BUNDLE_MAKEFILE + "INDEX_TITLE := Practicals, RL\n"

HEADED_SOURCE = textwrap.dedent(
    """
    # ---
    # jupyter:
    #   metadata:
    #     practical_name: Deep Q-Network
    #     practical_description: From the table to a network
    # ---

    # %%
    answer = 42
    """
).lstrip()


def _indexed_course(tmp_path, **kwargs):
    """A course with an index page and one source carrying a real header."""
    course = _course(tmp_path, names=("tp1",), makefile_head=INDEX_MAKEFILE, **kwargs)
    source = course / "sources" / "tp1.py"
    source.write_text(HEADED_SOURCE)
    _age(source)
    return course


@pytest.mark.skipif(shutil.which("zip") is None, reason="zip is not available")
def test_index_lists_the_practicals_their_files_and_the_archive(tmp_path):
    course = _indexed_course(tmp_path)
    _make(course, "index")

    page = (course / "student" / "index.html").read_text()
    assert "<h1>Practicals, RL</h1>" in page
    # the header's name and description, not the file name
    assert "Deep Q-Network" in page
    assert "From the table to a network" in page
    assert 'href="local/tp1.ipynb"' in page
    assert 'href="colab/tp1.ipynb"' in page
    # the archive, with the size it actually has
    assert 'href="tp.zip"' in page
    assert "Notebooks and environment" in page


@pytest.mark.skipif(shutil.which("zip") is None, reason="zip is not available")
def test_student_leaves_the_index_alone(tmp_path):
    """Building the notebooks is not handing them out: only `index` writes it."""
    course = _indexed_course(tmp_path)
    _make(course, "student")
    assert not (course / "student" / "index.html").exists()

    _make(course, "index")
    assert (course / "student" / "index.html").exists()


@pytest.mark.skipif(shutil.which("zip") is None, reason="zip is not available")
def test_a_course_can_ask_student_to_build_it(tmp_path):
    course = _indexed_course(tmp_path, makefile_extra="student: index\n")
    _make(course, "student")
    assert (course / "student" / "index.html").exists()


def test_rsync_builds_the_page_it_deploys(tmp_path):
    course = _course(tmp_path, names=("tp1",), makefile_head=INDEX_MAKEFILE)
    out = _make(course, "-n", "rsync", "SSH_HOST=h", "SSH_PATH=/p")
    assert "jupytext_notebook_helper.index" in out.stdout

    (tmp_path / "plain").mkdir()
    plain = _course(tmp_path / "plain", names=("tp1",), makefile_head=BUNDLE_MAKEFILE)
    out = _make(plain, "-n", "rsync", "SSH_HOST=h", "SSH_PATH=/p")
    assert "jupytext_notebook_helper.index" not in out.stdout


@pytest.mark.skipif(shutil.which("zip") is None, reason="zip is not available")
def test_an_unchanged_course_leaves_the_index_file_alone(tmp_path):
    course = _indexed_course(tmp_path)
    _make(course, "index")
    page = course / "student" / "index.html"
    before = page.stat().st_mtime
    _age(page)
    _make(course, "index")
    # rewritten bytes would be a new timestamp, and one more rsync upload
    assert page.stat().st_mtime < before


@pytest.mark.skipif(shutil.which("zip") is None, reason="zip is not available")
def test_the_index_follows_a_renamed_practical(tmp_path):
    course = _indexed_course(tmp_path)
    _make(course, "index")
    _age(course / "student" / "index.html")
    source = course / "sources" / "tp1.py"
    source.write_text(HEADED_SOURCE.replace("Deep Q-Network", "DQN, at last"))
    _make(course, "index")
    page = (course / "student" / "index.html").read_text()
    assert "DQN, at last" in page
    assert "Deep Q-Network" not in page


@pytest.mark.skipif(shutil.which("zip") is None, reason="zip is not available")
def test_the_archive_wording_is_the_course_own(tmp_path):
    course = _indexed_course(tmp_path)
    _make(course, "index", "INDEX_STUDENT_LABEL=Tout le TP, avec uv")
    page = (course / "student" / "index.html").read_text()
    assert "Tout le TP, avec uv" in page


def test_index_without_a_title_says_so(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    out = _make(course, "index", "INDEX_ZIPS=", check=False)
    assert out.returncode != 0
    assert "INDEX_TITLE is not set" in out.stdout + out.stderr


def test_rsync_carries_the_index_page(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    assert '--include "*.html"' in _rsync_line(course)


@pytest.mark.skipif(shutil.which("zip") is None, reason="zip is not available")
def test_clean_takes_the_index_page_down(tmp_path):
    course = _indexed_course(tmp_path)
    _make(course, "index")
    _make(course, "clean")
    assert not (course / "student" / "index.html").exists()


# --------------------------------------------------------------------------
# publish-git
# --------------------------------------------------------------------------


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


def _remote(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(remote)], check=True)
    return remote


def _publish(course, remote, *overrides):
    return _make(
        course,
        "publish-git",
        f"GIT_PUBLISH_URL={remote}",
        "GIT_PUBLISH_ENV=no",
        *overrides,
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not available")
def test_publish_git_commits_the_student_tree_without_pushing(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    remote = _remote(tmp_path)

    out = _publish(course, remote)

    clone = course / "outputs" / "git-publish"
    assert (clone / "local" / "tp1.ipynb").exists()
    assert (clone / "colab" / "tp1.ipynb").exists()
    assert _git(clone, "log", "--oneline").count("\n") == 1
    # the whole point of the split: nothing reached the remote (`show-ref`
    # exits 1 when a repository has no reference at all)
    bare = subprocess.run(
        ["git", "-C", str(remote), "show-ref"], capture_output=True, text=True
    )
    assert bare.stdout == ""
    assert "publish-git-push" in out.stdout


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not available")
def test_publish_git_push_is_what_publishes(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    remote = _remote(tmp_path)

    _publish(course, remote)
    _make(course, "publish-git-push", f"GIT_PUBLISH_URL={remote}")

    assert _git(remote, "rev-parse", "main")
    assert "tp1.ipynb" in _git(remote, "ls-tree", "-r", "--name-only", "main")


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not available")
def test_publish_git_is_idempotent_and_follows_a_deleted_source(tmp_path):
    course = _course(tmp_path, names=("tp1", "tp2"))
    remote = _remote(tmp_path)
    clone = course / "outputs" / "git-publish"

    _publish(course, remote)
    again = _publish(course, remote)
    assert "nothing changed" in again.stdout
    assert _git(clone, "log", "--oneline").count("\n") == 1

    (course / "sources" / "tp2.py").unlink()
    _make(course, "clean")
    _publish(course, remote)
    assert not (clone / "local" / "tp2.ipynb").exists()
    assert not (clone / "colab" / "tp2.ipynb").exists()
    assert (clone / "local" / "tp1.ipynb").exists()
    assert _git(clone, "log", "--oneline").count("\n") == 2


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not available")
def test_publish_git_leaves_the_repository_own_files_alone(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    remote = _remote(tmp_path)
    clone = course / "outputs" / "git-publish"

    _publish(course, remote)
    (clone / "LICENSE").write_text("CC-BY\n")
    (clone / ".gitignore").write_text(".venv/\n")
    _publish(course, remote)

    assert (clone / "LICENSE").read_text() == "CC-BY\n"
    assert (clone / ".gitignore").read_text() == ".venv/\n"


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not available")
def test_publish_git_ships_the_uv_environment_and_the_released_corrige(tmp_path):
    course = _course(tmp_path, names=("tp1",), makefile_head=SOLUTION_MAKEFILE)
    remote = _remote(tmp_path)
    clone = course / "outputs" / "git-publish"

    _make(course, "publish-git", f"GIT_PUBLISH_URL={remote}", "PUBLISH_SOLUTIONS=yes")

    # a clone is a working uv project, not just a directory of notebooks
    assert (clone / "pyproject.toml").exists()
    assert (clone / "uv.lock").exists()
    assert (clone / "README.md").read_text() == "# TP\n"
    assert (clone / "solution" / "local" / "tp1.ipynb").exists()
    assert (clone / "solution" / "colab" / "tp1.ipynb").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not available")
def test_publish_git_holds_the_corrige_back_until_it_is_released(tmp_path):
    course = _course(tmp_path, names=("tp1",), makefile_head=SOLUTION_MAKEFILE)
    remote = _remote(tmp_path)

    _make(course, "publish-git", f"GIT_PUBLISH_URL={remote}")

    assert not (course / "outputs" / "git-publish" / "solution").exists()


def test_publish_git_does_not_exist_without_a_repository(tmp_path):
    course = _course(tmp_path, names=("tp1",))
    failed = _make(course, "-n", "publish-git", check=False)
    assert failed.returncode != 0
    assert "publish-git" in failed.stderr


def test_manifest_colab_entries_open_in_colab_when_published_on_github(tmp_path):
    import json

    course = _course(tmp_path, names=("tp1",))
    _make(
        course,
        "manifest",
        "MANIFEST=practicals.json",
        "GIT_PUBLISH_URL=git@github.com:bpiwowar/course-lab.git",
    )
    written = json.loads((course / "practicals.json").read_text())
    files = written["practicals"][0]["files"]
    assert "url" not in files[0]
    assert files[1]["url"] == (
        "https://colab.research.google.com/github/bpiwowar/course-lab/blob/main/"
        "colab/tp1.ipynb"
    )
