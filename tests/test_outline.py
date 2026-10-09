from jupytext_notebook_helper import outline

SOURCE = """\
# %% [markdown]
# # Affinage LoRA d'un petit décodeur

# %% [markdown]
# ## Mise en place

# %% [markdown]
# ## Exercice 1 : LoRA à la main

# %%
print_header("EXERCICE 1")

# %%
# [[student]] Initialiser les matrices LoRA A et B
a = None
# [[/student]]

# %%
# [[student]] Implémenter le passage avant de LoRA
# [[assert]] dimensions incorrectes
b = None
# [[/student]]

# %%
# [[student]]
c = None
# [[/student]]
"""


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_extract_items_collects_headers_and_student_markers(tmp_path):
    source = write(tmp_path, "lora-sft.py", SOURCE)
    items = outline.extract_items(source)
    kinds = [(item.kind, item.level, item.text) for item in items]
    assert kinds == [
        ("header", 1, "Affinage LoRA d'un petit décodeur"),
        ("header", 2, "Mise en place"),
        ("header", 2, "Exercice 1 : LoRA à la main"),
        ("header", 3, "EXERCICE 1"),
        ("student", 0, "Initialiser les matrices LoRA A et B"),
        ("student", 0, "Implémenter le passage avant de LoRA"),
        ("assert", 0, "dimensions incorrectes"),
        ("student", 0, "(no description)"),
    ]


def test_format_outline_nests_tasks_under_the_last_header(tmp_path):
    source = write(tmp_path, "lora-sft.py", SOURCE)
    text = outline.format_outline("lora-sft", outline.extract_items(source))
    assert text.splitlines() == [
        "lora-sft (4 headers, 3 student tasks)",
        "# Affinage LoRA d'un petit décodeur",
        "  ## Mise en place",
        "  ## Exercice 1 : LoRA à la main",
        "    ### EXERCICE 1",
        "      - [ ] Initialiser les matrices LoRA A et B",
        "      - [ ] Implémenter le passage avant de LoRA",
        "        assert: dimensions incorrectes",
        "      - [ ] (no description)",
    ]


def test_main_lists_every_source_sorted(tmp_path, capsys):
    write(tmp_path, "lora-sft.py", SOURCE)
    write(tmp_path, "dpo.py", "# %%\nprint(1)\n")
    assert outline.main(["--sources", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.index("dpo (0 headers, 0 student tasks)") < out.index("lora-sft (")


def test_main_follows_the_course_order(tmp_path, capsys):
    write(tmp_path, "lora-sft.py", SOURCE)
    write(tmp_path, "dpo.py", "# %%\nprint(1)\n")
    assert outline.main(["--sources", str(tmp_path), "--order", "lora-sft dpo"]) == 0
    out = capsys.readouterr().out
    assert out.index("lora-sft (") < out.index("dpo (0 headers, 0 student tasks)")


def test_main_can_restrict_to_named_notebooks(tmp_path, capsys):
    write(tmp_path, "lora-sft.py", SOURCE)
    write(tmp_path, "dpo.py", "# %%\nprint(1)\n")
    assert outline.main(["--sources", str(tmp_path), "dpo"]) == 0
    out = capsys.readouterr().out
    assert "dpo" in out and "lora-sft" not in out


def test_main_rejects_an_unknown_notebook_name(tmp_path):
    write(tmp_path, "dpo.py", "# %%\nprint(1)\n")
    try:
        outline.main(["--sources", str(tmp_path), "nope"])
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert "nope" in str(exc)


def test_main_writes_to_a_file_when_asked(tmp_path):
    write(tmp_path, "dpo.py", "# %%\nprint(1)\n")
    output = tmp_path / "out" / "outline.txt"
    assert outline.main(["--sources", str(tmp_path), "--output", str(output)]) == 0
    assert "dpo (0 headers, 0 student tasks)" in output.read_text(encoding="utf-8")


def test_main_lists_notebooks_under_their_group(tmp_path, capsys):
    write(tmp_path, "lora-sft.py", SOURCE)
    write(tmp_path, "dpo.py", "# %%\nprint(1)\n")
    write(tmp_path, "extra.py", "# %%\nprint(1)\n")
    groups = tmp_path / "groups.json"
    groups.write_text(
        '[{"title": "Lecture 7", "names": [{"id": "dpo", "optional": true}]},'
        ' {"title": "Lecture 3", "names": ["lora-sft"]},'
        ' {"title": "Empty", "names": ["missing"]}]',
        encoding="utf-8",
    )
    sources = tmp_path / "sources"
    sources.mkdir()
    for name in ("lora-sft.py", "dpo.py", "extra.py"):
        (tmp_path / name).rename(sources / name)
    assert outline.main(["--sources", str(sources), "--groups", str(groups)]) == 0
    out = capsys.readouterr().out
    assert "\033" not in out
    assert out.index("== Lecture 7 ==") < out.index("dpo (optional) (0 headers")
    assert out.index("dpo (") < out.index("== Lecture 3 ==") < out.index("lora-sft (")
    assert "Empty" not in out
    assert (
        out.index("lora-sft (")
        < out.index("== Other practicals ==")
        < out.index("extra (")
    )


def test_main_colours_on_request(tmp_path, capsys):
    write(tmp_path, "dpo.py", "# %%\nprint(1)\n")
    assert outline.main(["--sources", str(tmp_path), "--color", "always"]) == 0
    assert "\033[1;36mdpo\033[0m" in capsys.readouterr().out
