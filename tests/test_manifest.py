import json

import pytest

from jupytext_notebook_helper import manifest

HEADER = """\
# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#   metadata:
#     practical_name: Affinage LoRA d'un décodeur
# ---

# %%
print("hello")
"""


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_display_name_from_header(tmp_path):
    source = write(tmp_path, "lora-sft.py", HEADER)
    assert manifest.display_name(source, "practical_name") == (
        "Affinage LoRA d'un décodeur"
    )


def test_display_name_falls_back_to_the_file_name(tmp_path):
    source = write(tmp_path, "security-threats.py", "# %%\nprint(1)\n")
    assert manifest.display_name(source, "practical_name") == "Security Threats"


def test_display_name_without_the_key(tmp_path):
    header = HEADER.replace("#     practical_name: Affinage LoRA d'un décodeur\n", "")
    source = write(tmp_path, "dpo.py", header)
    assert manifest.display_name(source, "practical_name") == "Dpo"


@pytest.mark.parametrize(
    "deploy,reader,expected",
    [
        ("h:/srv/course/lab", "h:/srv/course/slides", "../lab/"),
        ("/srv/course/lab", "/srv/course/slides", "../lab/"),
        ("h:/srv/course/slides", "h:/srv/course/slides", ""),
        ("h:/srv/course/lab/tp", "h:/srv/course/lab", "tp/"),
    ],
)
def test_base_url_is_derived_from_the_two_destinations(deploy, reader, expected):
    assert manifest.base_url(given=None, deploy_path=deploy, relative_to=reader) == (
        expected
    )


def test_base_url_given_outright_gains_a_trailing_slash():
    assert manifest.base_url(given="../lab", deploy_path=None, relative_to=None) == (
        "../lab/"
    )


def test_base_url_refuses_two_hosts():
    with pytest.raises(SystemExit):
        manifest.base_url(
            given=None, deploy_path="a:/srv/lab", relative_to="b:/srv/slides"
        )


def test_build_lists_every_source_sorted(tmp_path):
    write(tmp_path, "lora-sft.py", HEADER)
    write(tmp_path, "dpo.py", "# %%\n")
    built = manifest.build(
        sources_dir=tmp_path,
        colab_subdir="colab",
        local_label="Notebook",
        colab_label="Colab",
        name_key="practical_name",
        url="../lab/",
    )
    assert [p["id"] for p in built["practicals"]] == ["dpo", "lora-sft"]
    assert built["practicals"][1]["files"] == [
        {"label": "Notebook", "path": "lora-sft.ipynb"},
        {"label": "Colab", "path": "colab/lora-sft.ipynb"},
    ]


def test_write_if_changed_leaves_an_identical_file_alone(tmp_path):
    output = tmp_path / "practicals.json"
    built = {"version": 1, "baseUrl": "", "practicals": []}
    assert manifest.write_if_changed(output, built) is True
    assert manifest.write_if_changed(output, built) is False
    assert json.loads(output.read_text(encoding="utf-8")) == built


def test_build_leaves_bundles_and_solutions_out_by_default(tmp_path):
    write(tmp_path, "tp1.py", "# %%\n")
    built = manifest.build(
        sources_dir=tmp_path,
        colab_subdir="colab",
        local_label="Notebook",
        colab_label="Colab",
        name_key="practical_name",
        url="",
    )
    assert "bundles" not in built
    assert [f["path"] for f in built["practicals"][0]["files"]] == [
        "tp1.ipynb",
        "colab/tp1.ipynb",
    ]


def test_build_lists_bundles_and_solution_files(tmp_path):
    write(tmp_path, "tp1.py", "# %%\n")
    built = manifest.build(
        sources_dir=tmp_path,
        colab_subdir="colab",
        local_label="Notebook",
        colab_label="Colab",
        name_key="practical_name",
        url="../lab/",
        bundles=[manifest.parse_bundle("student=tp.zip")],
        solution_subdir="solution",
        solution_label="Corrigé",
        solution_colab_label="Corrigé (Colab)",
    )
    assert built["bundles"] == [{"id": "student", "path": "tp.zip"}]
    assert built["practicals"][0]["files"][2:] == [
        {"label": "Corrigé", "path": "solution/tp1.ipynb", "solution": True},
        {
            "label": "Corrigé (Colab)",
            "path": "solution/colab/tp1.ipynb",
            "solution": True,
        },
    ]
    # the keys stay in reading order: bundles before the (long) practicals list
    assert list(built) == ["version", "baseUrl", "bundles", "practicals"]


@pytest.mark.parametrize("value", ["student", "=tp.zip", "student="])
def test_parse_bundle_rejects_a_malformed_value(value):
    with pytest.raises(SystemExit):
        manifest.parse_bundle(value)
