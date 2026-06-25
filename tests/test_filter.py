"""Integration tests for the notebook filter (run via the CLI)."""

import json
import subprocess
import sys
import textwrap

SAMPLE = textwrap.dedent(
    '''
    # %% [markdown]
    # # Sample notebook

    # %% tags=["teacher"]
    secret = "teacher-only"

    # %%
    # [[student]] implement the answer
    # >x = 0
    answer = 42
    # [[/student]]
    '''
).lstrip()


def _run(args, src_path):
    proc = subprocess.run(
        [sys.executable, "-m", "jupytext_notebook_helper.filter", *args, str(src_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def _text(nb):
    return "\n".join("".join(c["source"]) for c in nb["cells"])


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
