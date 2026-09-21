"""Which practicals are handed out, and which of them with their corrigé.

A course does not hand out everything in ``sources/``. A practical may be
half-written, kept for next year, or replaced by a newer version that lives
next to it; its corrigé is usually released weeks after the practical itself,
one at a time. Both are properties of *that practical*, so they are written in
its own header rather than in a list somewhere else that rots::

    # ---
    # jupyter:
    #   metadata:
    #     practical_name: "Dynamic programming"
    #     practical_description: "Value iteration and policy iteration"
    #     publish: no          # not handed out (still built for the teacher)
    #     solution: yes        # ... but its corrigé is released
    # ---

``publish`` (default yes)
    Whether the practical is handed out: the student notebooks, the bundle,
    the index page, the manifest and ``rsync``. A source that says *no* is
    still built for the teacher and still run by ``make check`` — holding a
    practical back must not let it rot.
``solution`` (default: the course's ``PUBLISH_SOLUTIONS``)
    Whether its corrigé is released. The header always wins over the course
    default, so a single practical can be released early (``solution: yes``
    under ``PUBLISH_SOLUTIONS := no``) or held back (``solution: no`` under
    ``PUBLISH_SOLUTIONS := yes``). An unpublished practical never releases a
    corrigé, whatever its header says.

``tp.mk`` reads both lists in one go at parse time (``--format tags``), and
``make show-selection`` prints them for a human.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from jupytext_notebook_helper.header import read_header

#: Header key gating the hand-out, and its default.
PUBLISH_KEY = "publish"
#: Header key gating the corrigé; its default is the course's.
SOLUTION_KEY = "solution"

_TRUE = {"yes", "y", "true", "on", "1"}
_FALSE = {"no", "n", "false", "off", "0"}


def parse_bool(value: Any, *, what: str) -> Optional[bool]:
    """A header value as a boolean, or ``None`` when it says nothing.

    YAML reads a bare ``no`` as ``False`` already; a quoted ``"no"`` — which
    is what a header written defensively looks like, since a ``: `` in an
    unquoted scalar eats the rest of the line — arrives as a string.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        # `publish: 0` — YAML reads it as an integer, the Makefile spelling of
        # the same switch reads it as a no.
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
    print(  # noqa: T201
        f"warning: {what}: expected yes or no, got {value!r} — ignoring",
        file=sys.stderr,
    )
    return None


def flag(source: Path, key: str, *, default: bool) -> bool:
    """A boolean of the source's ``jupyter.metadata`` header, or ``default``."""
    header = read_header(source)
    jupyter = header.get("jupyter") if isinstance(header, dict) else None
    metadata = jupyter.get("metadata") if isinstance(jupyter, dict) else None
    if not isinstance(metadata, dict) or key not in metadata:
        return default
    parsed = parse_bool(metadata[key], what=f"{source}: {key}")
    return default if parsed is None else parsed


def is_published(source: Path) -> bool:
    """Whether the practical is handed out to the students."""
    return flag(source, PUBLISH_KEY, default=True)


def has_solution(source: Path, *, default: bool) -> bool:
    """Whether its corrigé is released; never for an unpublished practical."""
    return is_published(source) and flag(source, SOLUTION_KEY, default=default)


def sources(sources_dir: Path) -> List[Path]:
    """Every source of the course, in the order the practicals are numbered."""
    return sorted(Path(sources_dir).glob("*.py"))


def select(
    sources_dir: Path, *, solutions_default: bool
) -> Tuple[List[Path], List[Path]]:
    """The published sources, and those releasing their corrigé."""
    published, solutions = [], []
    for source in sources(sources_dir):
        if not is_published(source):
            continue
        published.append(source)
        if has_solution(source, default=solutions_default):
            solutions.append(source)
    return published, solutions


def _stems(paths: Iterable[Path]) -> List[str]:
    return [path.stem for path in paths]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m jupytext_notebook_helper.selection",
        description="List the practicals that are handed out, and their corrigés",
    )
    parser.add_argument("--sources", type=Path, default=Path("sources"))
    parser.add_argument(
        "--solutions-default",
        choices=("yes", "no"),
        default="no",
        help="whether a source whose header says nothing releases its corrigé "
        "(the course's PUBLISH_SOLUTIONS; default: no)",
    )
    parser.add_argument(
        "--format",
        choices=("tags", "published", "solutions", "held-back", "report"),
        default="tags",
        help="tags: `P:<name>` / `S:<name>` tokens, for make; the others print "
        "one name per line (report: a human-readable summary)",
    )
    args = parser.parse_args(argv)

    all_sources = sources(args.sources)
    published, solutions = select(
        args.sources, solutions_default=args.solutions_default == "yes"
    )
    published_stems = set(_stems(published))
    held_back = [source for source in all_sources if source.stem not in published_stems]

    if args.format == "tags":
        print(  # noqa: T201
            " ".join(
                [f"P:{stem}" for stem in _stems(published)]
                + [f"S:{stem}" for stem in _stems(solutions)]
            )
        )
        return 0
    if args.format == "report":
        solution_stems = set(_stems(solutions))
        for source in all_sources:
            if source.stem not in published_stems:
                state = "held back"
            elif source.stem in solution_stems:
                state = "published, with its corrigé"
            else:
                state = "published"
            print(f"  {source.stem:<40} {state}")  # noqa: T201
        return 0

    chosen = {
        "published": published,
        "solutions": solutions,
        "held-back": held_back,
    }[args.format]
    for stem in _stems(chosen):
        print(stem)  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
