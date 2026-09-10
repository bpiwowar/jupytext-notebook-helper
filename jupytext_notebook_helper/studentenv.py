"""Write the student environment's ``pyproject.toml``.

The bundle ships a minimal project generated from the union of the per-notebook
``.pkgs`` manifests (written by the filter when it builds the Colab variant),
plus a small base — never the course's own ``pyproject.toml``, which carries
editable and instructor-only dependencies that break ``uv sync`` once unzipped
somewhere else.

Requirements are deduplicated by project name, and a constrained requirement
wins over a bare one: a notebook importing ``cached_hub`` contributes
``cached-hub``, while the course can pin a floor with

    [tool.jupytext-notebook-helper]
    student-base-deps = ["cached-hub>=0.3.0"]

and the generated project lists the floor alone. Without it, ``uv lock`` is
free to keep whatever version it resolved first.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Iterable, List, Sequence

from . import config as course_config

#: Start of a requirement's version/marker/extras part.
_SPECIFIER = re.compile(r"[\[<>=!~;@\s]")


def _project_name(requirement: str) -> str:
    """``cached-hub>=0.3.0`` -> ``cached-hub``, PEP 503 normalised."""
    name = _SPECIFIER.split(requirement.strip(), 1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def merge_requirements(*groups: Iterable[str]) -> List[str]:
    """Union the groups, keeping one requirement per project name.

    A requirement carrying a specifier wins over a bare name; between two
    constrained ones the first seen wins (groups are passed most-specific last,
    so a later pin replaces an earlier bare name but not another pin).
    """
    chosen: dict[str, str] = {}
    for group in groups:
        for requirement in group:
            requirement = requirement.strip()
            if not requirement or requirement.startswith("#"):
                continue
            name = _project_name(requirement)
            if not name:
                continue
            current = chosen.get(name)
            if current is None:
                chosen[name] = requirement
            elif _SPECIFIER.search(current) is None and _SPECIFIER.search(requirement):
                chosen[name] = requirement  # the constrained one is more useful
            elif current != requirement and _SPECIFIER.search(current):
                logging.warning(
                    "student env: keeping %r, ignoring %r", current, requirement
                )
    return sorted(chosen.values(), key=_project_name)


class NoManifests(Exception):
    """No ``*.pkgs`` to read: the student environment would come out empty."""


def read_manifests(depdir: Path) -> List[str]:
    """Every package named by the per-notebook ``*.pkgs`` manifests.

    The manifests are written as a side effect of building the Colab variants,
    so deleting the dependency directory while the notebooks stay up to date
    leaves nothing to read — and an environment holding only the base packages
    would install none of what the practicals import. That is a build error,
    not something to paper over.
    """
    packages: List[str] = []
    for manifest in sorted(depdir.glob("*.pkgs")):
        packages.extend(manifest.read_text(encoding="utf-8").splitlines())
    if not packages:
        raise NoManifests(
            f"no package manifest in {depdir}: the Colab variants write them, so "
            "rebuild them first (`touch <sources>/*.py` when they look up to date)"
        )
    return packages


def render(name: str, requires_python: str, requirements: Sequence[str]) -> str:
    """The generated project file, as text."""
    lines = [
        "[project]",
        f'name = "{name}"',
        'version = "0.1.0"',
        f'requires-python = "{requires_python}"',
        "dependencies = [",
        *(f'    "{requirement}",' for requirement in requirements),
        "]",
        "",
        "[tool.uv]",
        "package = false",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depdir", type=Path, default=Path(".deps"))
    parser.add_argument(
        "--uv-root",
        type=Path,
        default=Path("."),
        help="directory holding the course pyproject.toml (its "
        "[tool.jupytext-notebook-helper] table is read)",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--name", help="project name (default: from the config)")
    parser.add_argument(
        "--requires-python", help="requires-python (default: from the config)"
    )
    parser.add_argument(
        "--base-dep",
        action="append",
        default=[],
        metavar="REQUIREMENT",
        help="requirement to add whatever the notebooks import (repeatable); "
        "added to the config's student-base-deps",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PACKAGE",
        help="package to leave out (repeatable); added to the config's pip-exclude",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="write the file even when no *.pkgs manifest was found",
    )
    args = parser.parse_args(argv)

    config = course_config.load(args.uv_root)
    base = list(course_config.DEFAULT_STUDENT_BASE_DEPS)
    base += config.student_base_deps + args.base_dep
    excluded = {
        _project_name(package) for package in (config.pip_exclude + args.exclude)
    }

    try:
        manifests = read_manifests(args.depdir)
    except NoManifests as exc:
        if not args.allow_empty:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        logging.warning("%s", exc)
        manifests = []

    requirements = [
        requirement
        for requirement in merge_requirements(manifests, base)
        if _project_name(requirement) not in excluded
    ]

    content = render(
        args.name or config.student_env_name,
        args.requires_python or config.student_requires_python,
        requirements,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.is_file() and args.output.read_text(encoding="utf-8") == content:
        return 0
    args.output.write_text(content, encoding="utf-8")
    print(
        f"Generated {args.output} from notebook imports ({args.depdir}/*.pkgs + base)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
