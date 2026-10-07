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


def test_an_order_puts_its_names_first_and_the_rest_by_file_name(tmp_path):
    for name in ("attention.py", "dpo.py", "intro.py", "zoo.py"):
        write(tmp_path, name)
    ordered = selection.sources(Path(tmp_path), "intro attention nope intro")
    assert [path.stem for path in ordered] == ["intro", "attention", "dpo", "zoo"]


def test_an_order_may_be_a_list(tmp_path):
    for name in ("a.py", "b.py"):
        write(tmp_path, name)
    assert [p.stem for p in selection.sources(Path(tmp_path), ["b", "a"])] == ["b", "a"]


def test_select_follows_the_order(tmp_path):
    write(tmp_path, "a.py", solution="yes")
    write(tmp_path, "b.py", solution="yes")
    published, solutions = selection.select(
        Path(tmp_path), solutions_default=False, order="b a"
    )
    assert [p.stem for p in published] == ["b", "a"]
    assert [p.stem for p in solutions] == ["b", "a"]


def test_order_problems_reports_both_sides(tmp_path):
    for name in ("a.py", "b.py"):
        write(tmp_path, name)
    assert selection.order_problems(Path(tmp_path), "a ghost") == (["ghost"], ["b"])


def test_check_order_fails_on_an_unknown_name(tmp_path, capsys):
    write(tmp_path, "a.py")
    args = ["--sources", str(tmp_path), "--format", "check-order"]
    assert selection.main(args + ["--order", "a ghost"]) == 1
    assert "error: ghost" in capsys.readouterr().err


def test_check_order_warns_on_an_unlisted_source_unless_strict(tmp_path, capsys):
    write(tmp_path, "a.py")
    write(tmp_path, "b.py")
    args = ["--sources", str(tmp_path), "--format", "check-order", "--order", "a"]
    assert selection.main(args) == 0
    assert "warning: b" in capsys.readouterr().err
    assert selection.main(args + ["--strict"]) == 1
    assert "error: b" in capsys.readouterr().err


def test_the_tags_follow_the_order(tmp_path, capsys):
    write(tmp_path, "a.py")
    write(tmp_path, "b.py")
    selection.main(["--sources", str(tmp_path), "--order", "b a"])
    assert capsys.readouterr().out.split() == ["P:b", "P:a"]
