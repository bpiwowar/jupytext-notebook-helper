"""Tests for release.json, the description of the student bundle."""

import json
import time
import zipfile

from jupytext_notebook_helper.release import describe, main


def _zip(path, files, date=(2020, 1, 1, 0, 0, 0)):
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(zipfile.ZipInfo(name, date_time=date), content)
    return path


FILES = {
    "pyproject.toml": "[project]\nname = 'tp'\n",
    "uv.lock": "version = 1\n",
    "README.md": "# TP\n",
    "notebooks/tp1.ipynb": "{}",
}


def test_every_file_is_listed_with_its_hash(tmp_path):
    release = describe(_zip(tmp_path / "tp.zip", FILES), name="tp")
    assert sorted(release["files"]) == sorted(FILES)
    assert all(h.startswith("sha256:") for h in release["files"].values())
    assert release["env"] == ["pyproject.toml", "uv.lock"]
    assert release["lock"] == release["files"]["uv.lock"]
    assert release["bundle"]["path"] == "tp.zip"


def test_the_id_depends_on_the_content_only(tmp_path):
    one = describe(_zip(tmp_path / "a.zip", FILES), name="tp")
    two = describe(
        _zip(tmp_path / "b.zip", FILES, date=(2024, 5, 5, 5, 5, 6)), name="tp"
    )
    assert one["id"] == two["id"]
    assert one["bundle"]["sha256"] != two["bundle"]["sha256"]

    edited = dict(FILES, **{"notebooks/tp1.ipynb": '{"x": 1}'})
    three = describe(_zip(tmp_path / "c.zip", edited), name="tp")
    assert three["id"] != one["id"]


def test_an_env_only_bundle_has_no_lock_entry(tmp_path):
    release = describe(_zip(tmp_path / "tp.zip", {"README.md": "x"}), name="tp")
    assert release["env"] == [] and "lock" not in release


def test_a_rebuilt_bundle_keeps_created_but_refreshes_its_hash(tmp_path):
    out = tmp_path / "release.json"
    bundle = _zip(tmp_path / "tp.zip", FILES)
    main([str(bundle), "-o", str(out), "--name", "tp", "--source", "abc"])
    first = json.loads(out.read_text())

    time.sleep(1.1)
    _zip(bundle, FILES, date=(2024, 1, 1, 0, 0, 0))  # same content, new zip
    main([str(bundle), "-o", str(out), "--name", "tp", "--source", "def"])
    second = json.loads(out.read_text())
    assert second["created"] == first["created"]
    assert second["source"] == "abc"
    assert second["bundle"]["sha256"] != first["bundle"]["sha256"]

    _zip(bundle, dict(FILES, **{"README.md": "changed"}))
    main([str(bundle), "-o", str(out), "--name", "tp", "--source", "def"])
    third = json.loads(out.read_text())
    assert third["id"] != first["id"] and third["source"] == "def"


def test_a_release_names_the_room_environment_when_there_is_one(tmp_path):
    bundle = _zip(tmp_path / "tp.zip", FILES)
    assert "shared_env" not in describe(bundle, name="tp")
    out = tmp_path / "release.json"
    main([str(bundle), "-o", str(out), "--name", "tp", "--shared-env", "/room/env"])
    assert json.loads(out.read_text())["shared_env"] == "/room/env"
