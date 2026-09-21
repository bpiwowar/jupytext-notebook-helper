from pathlib import Path

import pytest

from jupytext_notebook_helper import selection

HEADER = """\
# ---
# jupyter:
#   metadata:
#     practical_name: A practical
{extra}\
# ---

# %%
print("hello")
"""


def write(tmp_path, name, **keys):
    extra = "".join(f"#     {key}: {value}\n" for key, value in keys.items())
    path = tmp_path / name
    path.write_text(HEADER.format(extra=extra), encoding="utf-8")
    return path


def test_a_source_is_published_unless_its_header_says_otherwise(tmp_path):
    assert selection.is_published(write(tmp_path, "a.py"))
    assert not selection.is_published(write(tmp_path, "b.py", publish="no"))
    assert selection.is_published(write(tmp_path, "c.py", publish="yes"))


def test_a_source_without_a_header_is_published(tmp_path):
    path = tmp_path / "plain.py"
    path.write_text("# %%\nprint(1)\n", encoding="utf-8")
    assert selection.is_published(path)


@pytest.mark.parametrize("value", ["no", '"no"', "'No'", "false", "0", "off"])
def test_the_quoted_and_the_bare_spelling_agree(tmp_path, value):
    # A header key is often quoted, since a `: ` in an unquoted YAML scalar
    # swallows the rest of the line — both spellings must mean the same thing.
    assert not selection.is_published(write(tmp_path, "a.py", publish=value))


def test_an_unreadable_value_warns_and_keeps_the_default(tmp_path, capsys):
    source = write(tmp_path, "a.py", publish="maybe")
    assert selection.is_published(source)
    assert "expected yes or no" in capsys.readouterr().err


def test_the_course_default_decides_a_silent_header(tmp_path):
    source = write(tmp_path, "a.py")
    assert not selection.has_solution(source, default=False)
    assert selection.has_solution(source, default=True)


def test_a_header_wins_over_the_course_default(tmp_path):
    early = write(tmp_path, "early.py", solution="yes")
    held = write(tmp_path, "held.py", solution="no")
    assert selection.has_solution(early, default=False)
    assert not selection.has_solution(held, default=True)


def test_an_unpublished_practical_releases_no_corrige(tmp_path):
    source = write(tmp_path, "a.py", publish="no", solution="yes")
    assert not selection.has_solution(source, default=True)


def test_select_returns_both_lists_in_file_order(tmp_path):
    write(tmp_path, "01-first.py")
    write(tmp_path, "02-second.py", solution="yes")
    write(tmp_path, "03-third.py", publish="no")
    published, solutions = selection.select(tmp_path, solutions_default=False)
    assert [path.stem for path in published] == ["01-first", "02-second"]
    assert [path.stem for path in solutions] == ["02-second"]


def test_the_tags_format_is_what_make_reads(tmp_path, capsys):
    write(tmp_path, "01-first.py")
    write(tmp_path, "02-second.py", solution="yes")
    write(tmp_path, "03-third.py", publish="no")
    selection.main(["--sources", str(tmp_path), "--format", "tags"])
    assert capsys.readouterr().out.split() == [
        "P:01-first",
        "P:02-second",
        "S:02-second",
    ]


def test_the_plain_formats_print_one_name_per_line(tmp_path, capsys):
    write(tmp_path, "01-first.py")
    write(tmp_path, "02-held.py", publish="no")
    selection.main(["--sources", str(tmp_path), "--format", "held-back"])
    assert capsys.readouterr().out.split() == ["02-held"]


def test_the_solutions_default_comes_from_the_command_line(tmp_path, capsys):
    write(tmp_path, "01-first.py")
    selection.main(
        ["--sources", str(tmp_path), "--solutions-default", "yes", "--format", "tags"]
    )
    assert "S:01-first" in capsys.readouterr().out


def test_sources_are_sorted(tmp_path):
    for name in ("10-later.py", "02-earlier.py"):
        write(tmp_path, name)
    assert [path.name for path in selection.sources(Path(tmp_path))] == [
        "02-earlier.py",
        "10-later.py",
    ]
