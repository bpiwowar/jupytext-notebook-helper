"""Describe the practicals as JSON, for whatever publishes them.

A course's notebooks are built here, but they are *announced* somewhere else —
a slide deck's index page, a course site, a syllabus. That consumer needs three
things this directory knows and it does not: which practicals exist, what each
one is called, and the URL each of its files ends up at. Writing them by hand
on the other side means a list that silently rots.

So this module writes them out::

    {
      "version": 1,
      "baseUrl": "../lab/",
      "practicals": [
        { "id": "lora-sft",
          "name": "Affinage LoRA d'un décodeur",
          "files": [
            { "label": "Notebook", "path": "lora-sft.ipynb" },
            { "label": "Colab",    "path": "colab/lora-sft.ipynb" }
          ] }
      ]
    }

``path`` is relative to ``baseUrl``, which is where ``make rsync`` puts the
notebooks as seen from the consumer. It is either given outright
(``--base-url``) or worked out from the two deployment paths
(``--deploy-path``, ``--relative-to``), so that neither side carries a URL it
cannot check.

The display name is the ``practical_name`` key of the source's percent-format
header::

    # ---
    # jupyter:
    #   metadata:
    #     practical_name: Affinage LoRA d'un décodeur
    # ---

and falls back to the file name, title-cased.

This reads the headers only: no notebook is built, so it is cheap enough to run
before every build of the consumer (`make manifest`).
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# A `host:` prefix on a deployment path (rsync's own syntax). A Windows drive
# letter is not a concern here: these are remote paths.
_HOST_PREFIX = re.compile(r"^(?P<host>[^/:]+):(?P<path>/.*)$")


def read_header(source: Path) -> dict[str, Any]:
    """The percent-format YAML header of a jupytext source, as a dict.

    Only the header is read — the comment block between the first two ``# ---``
    lines — so the cost does not grow with the notebook.
    """
    lines: list[str] = []
    started = False
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.rstrip("\n")
            if stripped == "# ---":
                if started:
                    break
                started = True
                continue
            if not started:
                # Anything before the header means there is none.
                if stripped.strip():
                    return {}
                continue
            if not stripped.startswith("#"):
                return {}
            lines.append(stripped[2:] if stripped.startswith("# ") else stripped[1:])
    if not lines:
        return {}
    try:
        header = yaml.safe_load("\n".join(lines))
    except yaml.YAMLError:
        return {}
    return header if isinstance(header, dict) else {}


def display_name(source: Path, name_key: str) -> str:
    """The practical's title, from the header, or the file name title-cased."""
    header = read_header(source)
    jupyter = header.get("jupyter") if isinstance(header, dict) else None
    if isinstance(jupyter, dict):
        metadata = jupyter.get("metadata")
        if isinstance(metadata, dict):
            value = metadata.get(name_key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return " ".join(word.capitalize() for word in source.stem.split("-"))


def base_url(
    *, given: str | None, deploy_path: str | None, relative_to: str | None
) -> str:
    """Where the notebooks are served from, as seen by the consumer.

    ``given`` wins. Otherwise the two deployment paths are compared: where
    ``make rsync`` puts the notebooks, and where the consumer puts itself. Both
    may carry an rsync ``host:`` prefix; a different host on each side has no
    relative URL, and says so rather than emitting a wrong one.
    """
    if given:
        return given if given.endswith("/") else given + "/"
    if not deploy_path or not relative_to:
        return ""

    hosts = []
    paths = []
    for value in (deploy_path, relative_to):
        match = _HOST_PREFIX.match(value)
        hosts.append(match.group("host") if match else None)
        paths.append(match.group("path") if match else value)
    if hosts[0] and hosts[1] and hosts[0] != hosts[1]:
        raise SystemExit(
            f"manifest: the practicals go to {hosts[0]} and their reader to "
            f"{hosts[1]} — no relative URL joins the two; set --base-url"
        )

    relative = posixpath.relpath(paths[0], paths[1])
    return "" if relative == "." else relative.rstrip("/") + "/"


def build(
    *,
    sources_dir: Path,
    colab_subdir: str,
    local_label: str,
    colab_label: str,
    name_key: str,
    url: str,
) -> dict[str, Any]:
    practicals = []
    for source in sorted(sources_dir.glob("*.py")):
        stem = source.stem
        files = [{"label": local_label, "path": f"{stem}.ipynb"}]
        if colab_subdir:
            files.append({"label": colab_label, "path": f"{colab_subdir}/{stem}.ipynb"})
        practicals.append(
            {"id": stem, "name": display_name(source, name_key), "files": files}
        )
    return {"version": 1, "baseUrl": url, "practicals": practicals}


def write_if_changed(output: Path, manifest: dict[str, Any]) -> bool:
    """Write the manifest, and say whether it actually changed.

    The consumer's build keys off this file's timestamp, so rewriting an
    identical manifest would rebuild it for nothing on every run.
    """
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if output.exists() and output.read_text(encoding="utf-8") == text:
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m jupytext_notebook_helper.manifest",
        description="Write a JSON description of the practicals",
    )
    parser.add_argument("--sources", type=Path, default=Path("sources"))
    parser.add_argument(
        "--colab-subdir",
        default="colab",
        help="sub-directory of the Colab variants; empty to leave them out",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--local-label", default="Notebook")
    parser.add_argument("--colab-label", default="Colab")
    parser.add_argument(
        "--name-key",
        default="practical_name",
        help="header key holding the display name (under jupyter.metadata)",
    )
    parser.add_argument(
        "--base-url", help="where the notebooks are served from, for the consumer"
    )
    parser.add_argument(
        "--deploy-path", help="where `make rsync` puts the notebooks (host:/path)"
    )
    parser.add_argument(
        "--relative-to", help="where the consumer puts itself (host:/path)"
    )
    args = parser.parse_args(argv)

    if not args.sources.is_dir():
        raise SystemExit(f"manifest: no sources directory at {args.sources}")

    manifest = build(
        sources_dir=args.sources,
        colab_subdir=args.colab_subdir,
        local_label=args.local_label,
        colab_label=args.colab_label,
        name_key=args.name_key,
        url=base_url(
            given=args.base_url,
            deploy_path=args.deploy_path,
            relative_to=args.relative_to,
        ),
    )
    changed = write_if_changed(args.output, manifest)
    count = len(manifest["practicals"])
    state = "written" if changed else "unchanged"
    print(f"{args.output}: {count} practicals, {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
