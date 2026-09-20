import json

import pytest

from jupytext_notebook_helper import index

MANIFEST = {
    "version": 1,
    "baseUrl": "",
    "bundles": [
        {"id": "student", "path": "tp-uv.zip"},
        {"id": "solution", "path": "tp-uv-solution.zip"},
    ],
    "practicals": [
        {
            "id": "01-dqn",
            "name": "Deep Q-Network",
            "description": "From the tabular table to a network",
            "files": [
                {"label": "Notebook", "path": "local/01-dqn.ipynb"},
                {
                    "label": "Colab",
                    "path": "colab/01-dqn.ipynb",
                    "url": "https://colab.research.google.com/github/o/r/blob/main/colab/01-dqn.ipynb",
                },
                {
                    "label": "Corrigé",
                    "path": "solution/local/01-dqn.ipynb",
                    "solution": True,
                },
            ],
        },
        {
            "id": "02-ppo",
            "name": "PPO",
            "files": [{"label": "Notebook", "path": "local/02-ppo.ipynb"}],
        },
    ],
}


def render(manifest=None, **kwargs):
    kwargs.setdefault("title", "Practicals")
    return index.render(manifest or MANIFEST, **kwargs)


def test_every_practical_gets_a_row_with_its_name_and_links():
    page = render()
    assert "Deep Q-Network" in page
    assert "From the tabular table to a network" in page
    assert 'href="local/01-dqn.ipynb"' in page
    assert 'href="local/02-ppo.ipynb"' in page


def test_a_colab_entry_uses_its_absolute_url():
    page = render()
    assert (
        'href="https://colab.research.google.com/github/o/r/blob/main/colab/01-dqn.ipynb"'
        in page
    )
    # ... and not the path it would otherwise be reached by
    assert 'href="colab/01-dqn.ipynb"' not in page


def test_paths_are_resolved_against_the_base_url():
    manifest = dict(MANIFEST, baseUrl="../lab/")
    page = render(manifest)
    assert 'href="../lab/local/02-ppo.ipynb"' in page


def test_a_solution_link_is_marked_as_one():
    page = render()
    assert '<a class="link solution" href="solution/local/01-dqn.ipynb"' in page


def test_the_archives_are_listed_with_their_default_wording():
    page = render()
    assert "Notebooks and environment" in page
    assert "Solutions" in page
    assert 'href="tp-uv.zip"' in page


def test_an_archive_can_be_renamed():
    page = render(bundle_labels={"student": "Tout le TP (uv)"})
    assert "Tout le TP (uv)" in page
    assert "Notebooks and environment" not in page


def test_an_unknown_archive_id_falls_back_to_the_id():
    manifest = dict(MANIFEST, bundles=[{"id": "slides-pack", "path": "s.zip"}])
    assert "Slides pack" in render(manifest)


def test_a_manifest_without_archives_has_no_download_section():
    manifest = {k: v for k, v in MANIFEST.items() if k != "bundles"}
    page = render(manifest)
    assert "<h2>Download</h2>" not in page
    assert "Deep Q-Network" in page


def test_the_description_column_is_left_out_when_no_source_has_one():
    manifest = dict(
        MANIFEST,
        practicals=[{"id": "x", "name": "X", "files": []}],
    )
    assert "Description" not in render(manifest)


def test_the_title_and_the_introduction_reach_the_page():
    page = render(title="RL — practicals", intro="<p>Python 3.11 or later.</p>")
    assert "<title>RL — practicals</title>" in page
    assert "<h1>RL — practicals</h1>" in page
    assert "<p>Python 3.11 or later.</p>" in page


def test_the_page_carries_no_external_resource():
    page = render()
    assert "<script" not in page
    assert "http://" not in page
    # the only absolute URL is the Colab link of the manifest itself
    assert page.count("https://") == 1


def test_names_are_escaped():
    manifest = dict(
        MANIFEST,
        practicals=[
            {"id": "x", "name": "A <b>bold</b> & risky title", "files": []},
        ],
    )
    page = render(manifest)
    assert "<b>bold</b>" not in page
    assert "A &lt;b&gt;bold&lt;/b&gt; &amp; risky title" in page


@pytest.mark.parametrize(
    "size,expected",
    [(0, "0 B"), (512, "512 B"), (1536, "1.5 kB"), (204800, "200 kB")],
)
def test_human_size(size, expected):
    assert index.human_size(size) == expected


def test_an_archive_that_is_here_is_listed_with_its_size(tmp_path):
    (tmp_path / "tp-uv.zip").write_bytes(b"x" * 1536)
    page = render(root=tmp_path)
    assert "1.5 kB" in page
    # the other one is not on disk: named, but without a size
    assert "tp-uv-solution.zip" in page


@pytest.mark.parametrize("value", ["student", "=label", "student="])
def test_parse_label_rejects_a_malformed_value(value):
    with pytest.raises(SystemExit):
        index.parse_label(value)


def test_main_writes_the_page(tmp_path, capsys):
    manifest = tmp_path / "practicals.json"
    manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
    output = tmp_path / "out" / "index.html"
    assert (
        index.main(
            [
                "--manifest",
                str(manifest),
                "--output",
                str(output),
                "--title",
                "TP",
                "--bundle-label",
                "student=Le zip",
                "--footer",
                "Sorbonne Université",
            ]
        )
        == 0
    )
    page = output.read_text(encoding="utf-8")
    assert "<h1>TP</h1>" in page
    assert "Le zip" in page
    assert "Sorbonne Université" in page
    assert "2 practicals, written" in capsys.readouterr().out


def test_main_leaves_an_identical_page_alone(tmp_path, capsys):
    manifest = tmp_path / "practicals.json"
    manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
    output = tmp_path / "index.html"
    args = ["--manifest", str(manifest), "--output", str(output), "--title", "TP"]
    index.main(args)
    capsys.readouterr()
    index.main(args)
    assert "unchanged" in capsys.readouterr().out


def test_main_refuses_a_missing_manifest(tmp_path):
    with pytest.raises(SystemExit):
        index.main(
            [
                "--manifest",
                str(tmp_path / "nope.json"),
                "--output",
                str(tmp_path / "index.html"),
            ]
        )


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("01-dynamic_programming", "01"),
        ("03-2-dqn-full", "03-2"),
        ("A01-environments", "A01"),
        ("15-time-extension-2025", "15"),
        ("intro", ""),
        ("12", "12"),
    ],
)
def test_practical_number(identifier, expected):
    assert index.practical_number(identifier) == expected


def test_the_number_column_holds_the_prefix_not_the_whole_file_name():
    page = render()
    assert '<td class="num">01</td>' in page
    assert "01-dqn</td>" not in page


def test_unnumbered_sources_get_no_number_column():
    manifest = dict(
        MANIFEST, practicals=[{"id": "intro", "name": "Intro", "files": []}]
    )
    page = render(manifest)
    assert '<th scope="col">#</th>' not in page
