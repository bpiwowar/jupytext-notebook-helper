"""Tests for the course config table and the generated student environment."""

import textwrap
from pathlib import Path

import pytest

from jupytext_notebook_helper import config as course_config
from jupytext_notebook_helper.studentenv import main, merge_requirements

CONFIG = """
[project]
name = "mycourse"
version = "0.1.0"

[tool.jupytext-notebook-helper]
pip-exclude = ["mycourse-internal"]
pip-force-include = ["torchvision"]
student-base-deps = ["cs-lab>=1.0"]
student-env-name = "tp-mycourse"
student-requires-python = ">=3.11"
"""


@pytest.fixture
def course(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(textwrap.dedent(CONFIG))
    depdir = tmp_path / ".deps"
    depdir.mkdir()
    (depdir / "01-intro.pkgs").write_text("torch\ncs-lab\nmycourse-internal\n")
    (depdir / "02-vlm.pkgs").write_text("torch\ntorchvision\ntransformers\n")
    return tmp_path


def test_config_is_read_from_the_tool_table(course):
    config = course_config.load(course)
    assert config.pip_force_include == ["torchvision"]
    assert config.pip_exclude == ["mycourse-internal"]
    assert config.student_base_deps == ["cs-lab>=1.0"]
    assert config.student_env_name == "tp-mycourse"
    assert config.student_requires_python == ">=3.11"


def test_config_defaults_without_a_table(tmp_path):
    config = course_config.load(tmp_path)
    assert config.pip_force_include == []
    assert config.student_env_name == course_config.DEFAULT_STUDENT_ENV_NAME


def test_config_warns_on_an_unknown_key(tmp_path, caplog):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.jupytext-notebook-helper]\npip_force_include = ['x']\n"
    )
    course_config.load(tmp_path)
    assert "unknown" in caplog.text


def test_config_warns_on_a_wrong_type(tmp_path, caplog):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.jupytext-notebook-helper]\npip-exclude = "not-a-list"\n'
    )
    assert course_config.load(tmp_path).pip_exclude == []
    assert "should be a list" in caplog.text


def test_a_constrained_requirement_wins_over_a_bare_one():
    assert merge_requirements(["cs-lab", "torch"], ["cs-lab>=1.0"]) == [
        "cs-lab>=1.0",
        "torch",
    ]
    # ... whichever side it comes from
    assert merge_requirements(["cs-lab>=1.0"], ["cs-lab"]) == ["cs-lab>=1.0"]


def test_merge_ignores_blanks_and_comments():
    assert merge_requirements(["", "  ", "# a note", "torch"]) == ["torch"]


def test_generated_project(course, tmp_path):
    output = tmp_path / "student-env" / "pyproject.toml"
    assert main(["--depdir", str(course / ".deps"), "--uv-root", str(course),
                 "--output", str(output)]) == 0  # fmt: skip
    text = output.read_text()

    assert 'name = "tp-mycourse"' in text
    assert 'requires-python = ">=3.11"' in text
    # notebook imports, deduplicated
    assert text.count('"torch",') == 1
    assert '"transformers",' in text
    # the base is always there, and the course's floor replaces the bare name
    assert '"jupyterlab",' in text
    assert '"cs-lab>=1.0",' in text
    assert '"cs-lab",' not in text
    # excluded packages never reach the students
    assert "mycourse-internal" not in text


def test_generated_project_is_stable(course, tmp_path, capsys):
    output = tmp_path / "env" / "pyproject.toml"
    argv = ["--depdir", str(course / ".deps"), "--uv-root", str(course),
            "--output", str(output)]  # fmt: skip
    main(argv)
    assert "Generated" in capsys.readouterr().out
    main(argv)
    assert capsys.readouterr().out == ""  # unchanged: no rewrite, no noise


def test_command_line_adds_to_the_config(course, tmp_path):
    output = tmp_path / "env" / "pyproject.toml"
    main(["--depdir", str(course / ".deps"), "--uv-root", str(course),
          "--output", str(output), "--base-dep", "seaborn", "--exclude", "torch"])  # fmt: skip
    text = output.read_text()
    assert '"seaborn",' in text
    assert '"torch",' not in text
    assert '"cs-lab>=1.0",' in text  # config still applies


def test_missing_manifests_is_an_error(course, tmp_path, capsys):
    for manifest in (course / ".deps").glob("*.pkgs"):
        manifest.unlink()
    output = tmp_path / "env" / "pyproject.toml"
    argv = ["--depdir", str(course / ".deps"), "--uv-root", str(course),
            "--output", str(output)]  # fmt: skip

    assert main(argv) == 1
    assert not output.exists()
    assert "rebuild them first" in capsys.readouterr().err

    assert main(argv + ["--allow-empty"]) == 0
    assert '"jupyterlab",' in output.read_text()
