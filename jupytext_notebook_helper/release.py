"""Describe the student bundle as a release: ``release.json``.

A student who unzipped the bundle and then worked in it cannot simply unzip
the next one on top. The updater (``cs-lab course update``) needs to know,
for every file of the new bundle, whether it changed since the version the
student has — so the release lists each file with its hash.

``id`` identifies the release by its content alone (a hash over the file
list), so rebuilding an unchanged bundle gives the same id even though the
zip itself, which stores timestamps, differs. ``created`` and ``source`` are
informative: when the release was described, and from which commit.

Paths are the ones inside the zip (``notebooks/<name>.ipynb``,
``pyproject.toml``, ...), which is also where they go in the student's folder.
``env`` names the files that make up the environment: the updater merges them
instead of treating them as content, and leaves them alone when the student
uses a shared environment.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Dict, Optional, Sequence

#: Bumped when the layout of release.json changes incompatibly.
FORMAT = 1

#: The files that make up the environment, when the bundle has them.
ENV_FILES = ("pyproject.toml", "uv.lock")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _files(bundle: Path) -> Dict[str, str]:
    """Each file of the zip, sorted, with its hash."""
    files: Dict[str, str] = {}
    with zipfile.ZipFile(bundle) as archive:
        for info in archive.infolist():
            if not info.is_dir():
                files[info.filename] = "sha256:" + _sha256(archive.read(info))
    return dict(sorted(files.items()))


def _id(files: Dict[str, str]) -> str:
    listing = "".join(f"{path}\0{digest}\n" for path, digest in files.items())
    return _sha256(listing.encode())[:16]


def release_id(bundle: Path) -> str:
    """The id of the release ``bundle`` makes: a hash of its content only."""
    return _id(_files(bundle))


def describe(
    bundle: Path,
    *,
    name: str,
    bundle_url: Optional[str] = None,
    source: Optional[str] = None,
    created: Optional[str] = None,
    shared_env: Optional[str] = None,
) -> dict:
    """The release.json content for ``bundle`` (a zip)."""
    files = _files(bundle)
    release = {
        "format": FORMAT,
        "name": name,
        "id": _id(files),
        "created": created
        or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bundle": {
            "path": bundle_url or bundle.name,
            "sha256": _sha256(bundle.read_bytes()),
        },
        "env": [path for path in ENV_FILES if path in files],
        "files": files,
    }
    if source:
        release["source"] = source
    if "uv.lock" in files:
        release["lock"] = files["uv.lock"]
    if shared_env:
        # A teaching room's environment for this release: `cs-lab course
        # init` uses it on a machine where this path exists.
        release["shared_env"] = shared_env
    return release


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bundle", type=Path, help="the student zip")
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument("--name", required=True, help="the course's release name")
    parser.add_argument(
        "--bundle-url",
        help="where the zip is, relative to release.json (default: its file name)",
    )
    parser.add_argument("--source", help="the source commit (informative)")
    parser.add_argument(
        "--shared-env",
        help="absolute path of a teaching room's environment for this release",
    )
    args = parser.parse_args(argv)

    previous = None
    if args.output.is_file():
        try:
            previous = json.loads(args.output.read_text(encoding="utf-8"))
        except ValueError:
            pass

    # The same content is the same release: it keeps its `created` (and
    # `source`). The zip may still have been rebuilt — it stores timestamps —
    # so its hash is refreshed all the same.
    created = None
    if previous and previous.get("id") == release_id(args.bundle):
        created = previous.get("created")
    release = describe(
        args.bundle,
        name=args.name,
        bundle_url=args.bundle_url,
        source=(previous or {}).get("source") if created else args.source,
        created=created,
        shared_env=args.shared_env,
    )

    content = json.dumps(release, indent=2, ensure_ascii=False) + "\n"
    if args.output.is_file() and args.output.read_text(encoding="utf-8") == content:
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")
    print(f"Described {args.bundle} in {args.output} (release {release['id']})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
