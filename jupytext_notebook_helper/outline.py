"""Outline of the practicals: header structure + student-facing tasks.

Answers a question that comes up before every session: what does each
notebook actually ask a student to do, and where. It walks a source's cells
in order and prints its Markdown headers (ATX ``#``/``##``/``###`` lines and
``print_header(...)`` calls, which the filter turns into a header too) with
each ``[[student]]``/``[[assert]]`` marker nested under the section it
appears in::

    lora-sft (4 headers, 3 student tasks)
    # Affinage LoRA d'un petit décodeur
      ## Mise en place
      ## Exercice 1 : LoRA à la main
        - [ ] Initialiser les matrices LoRA A et B
        - [ ] Implémenter le passage avant de LoRA
              assert: dimensions incorrectes
        - [ ] Optionnel : fusionner les poids

With ``--groups FILE`` the notebooks are listed under headings — e.g. the
lecture each one belongs to. FILE is JSON, a list of groups in order::

    [{"title": "Lecture 3: Efficient LLMs",
      "names": ["lora", {"id": "inference-cost", "optional": true}]}]

A source no group names comes last, under "Other practicals".

On a terminal (and unless NO_COLOR is set) the output is coloured;
``--color always|never`` forces it either way.

This reads the sources only: no notebook is built, so — like ``manifest`` —
it is cheap enough to run at any time, e.g. to review a practical's shape
before class or to spot a section with no work left for the student.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import jupytext

RE_ATX_HEADER = re.compile(r"""^(#{1,6})\s+(\S.*\S|\S)\s*$""")
RE_PRINT_HEADER = re.compile(r"""^print_header\s*\(\s*["'](.+?)["']\s*\)\s*$""")
RE_STUDENT_START = re.compile(
    r"""^(?:\s*)#(?:.*)\[\[STUDENT\]\]\s*(\S.*\S)?\s*$""", re.IGNORECASE
)
RE_ASSERT = re.compile(r"""^(?:\s*)#(?:.*)\[\[assert\]\]\s*(\S.*)$""", re.IGNORECASE)

from jupytext_notebook_helper import selection

#: Header level synthesized for a `print_header(...)` call (matches the `###`
#: the filter turns it into — see `filter.RE_PRINT_HEADER`).
PRINT_HEADER_LEVEL = 3


@dataclass(frozen=True)
class Style:
    """ANSI escapes for the parts of an outline (all empty: plain text)."""

    group: str = ""
    name: str = ""
    header: str = ""
    task: str = ""
    dim: str = ""
    reset: str = ""


PLAIN = Style()
COLOR = Style(
    group="\033[1;35m",
    name="\033[1;36m",
    header="\033[1m",
    task="\033[32m",
    dim="\033[2m",
    reset="\033[0m",
)


def pick_style(color: str, stream) -> Style:
    """`--color auto` colours a terminal, unless NO_COLOR is set."""
    if color == "always":
        return COLOR
    if color == "never":
        return PLAIN
    is_tty = getattr(stream, "isatty", lambda: False)()
    return COLOR if is_tty and not os.environ.get("NO_COLOR") else PLAIN


@dataclass
class Group:
    title: str
    names: list[str]
    optional: set[str]


def read_groups(path: Path) -> list[Group]:
    """The groups of a `--groups` JSON file (see the module docstring)."""
    groups = []
    for entry in json.loads(path.read_text(encoding="utf-8")):
        names, optional = [], set()
        for name in entry.get("names", []):
            if isinstance(name, dict):
                if name.get("optional"):
                    optional.add(name["id"])
                name = name["id"]
            names.append(name)
        groups.append(Group(entry["title"], names, optional))
    return groups


@dataclass
class Item:
    kind: str  # "header", "student" or "assert"
    level: int  # header depth (1-6); unused for "student"/"assert"
    text: str


def extract_items(source: Path) -> list[Item]:
    """The headers and student markers of one source, in document order."""
    document = jupytext.read(source, fmt="py:percent")
    items: list[Item] = []
    for cell in document["cells"]:
        lines = cell.get("source", "").split("\n")
        if cell["cell_type"] == "markdown":
            for line in lines:
                if m := RE_ATX_HEADER.match(line):
                    items.append(Item("header", len(m.group(1)), m.group(2)))
        else:
            for line in lines:
                if m := RE_PRINT_HEADER.match(line):
                    items.append(Item("header", PRINT_HEADER_LEVEL, m.group(1)))
                elif m := RE_STUDENT_START.match(line):
                    items.append(Item("student", 0, m.group(1) or "(no description)"))
                elif m := RE_ASSERT.match(line):
                    items.append(Item("assert", 0, m.group(1).strip()))
    return items


def format_outline(
    name: str, items: list[Item], style: Style = PLAIN, optional: bool = False
) -> str:
    """Render one source's outline as indented text."""
    st = style
    headers = sum(1 for item in items if item.kind == "header")
    tasks = sum(1 for item in items if item.kind == "student")
    lines = [
        f"{st.name}{name}{st.reset}"
        + (" (optional)" if optional else "")
        + f" {st.dim}({headers} headers, {tasks} student tasks){st.reset}"
    ]

    current_level = 0  # depth of the last header seen, for un-headed sources
    for item in items:
        if item.kind == "header":
            current_level = item.level
            indent = "  " * (item.level - 1)
            bold = st.header if item.level <= 2 else ""
            reset = st.reset if bold else ""
            lines.append(f"{indent}{bold}{'#' * item.level} {item.text}{reset}")
        elif item.kind == "student":
            indent = "  " * current_level
            lines.append(f"{indent}{st.task}- [ ] {item.text}{st.reset}")
        else:  # "assert"
            indent = "  " * (current_level + 1)
            lines.append(f"{indent}{st.dim}assert: {item.text}{st.reset}")
    return "\n".join(lines)


def format_groups(
    sources: list[Path], groups: list[Group], style: Style = PLAIN
) -> str:
    """The outlines of `sources`, under the heading of the group naming each."""
    by_name = {source.stem: source for source in sources}
    grouped = {name for group in groups for name in group.names}
    rest = [s.stem for s in sources if s.stem not in grouped]
    blocks = []
    for group in groups + ([Group("Other practicals", rest, set())] if rest else []):
        names = [name for name in group.names if name in by_name]
        if not names:
            continue
        blocks.append(f"{style.group}== {group.title} =={style.reset}")
        blocks.extend(
            format_outline(
                name,
                extract_items(by_name[name]),
                style,
                optional=name in group.optional,
            )
            for name in names
        )
    return "\n\n".join(blocks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m jupytext_notebook_helper.outline",
        description="Print each source's header structure and student tasks",
    )
    parser.add_argument("--sources", type=Path, default=Path("sources"))
    parser.add_argument(
        "--order",
        default="",
        help="the course order, as source names separated by blanks "
        "(default: file name order)",
    )
    parser.add_argument(
        "names", nargs="*", help="restrict to these notebooks (source stems)"
    )
    parser.add_argument(
        "--groups",
        type=Path,
        help="JSON list of {title, names} to list the notebooks under "
        "(see the module docstring)",
    )
    parser.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="colour the output (auto: on a terminal, unless NO_COLOR is set)",
    )
    parser.add_argument("--output", type=Path, help="write to a file instead of stdout")
    args = parser.parse_args(argv)

    if not args.sources.is_dir():
        raise SystemExit(f"outline: no sources directory at {args.sources}")

    sources = selection.sources(args.sources, args.order)
    if args.names:
        wanted = set(args.names)
        sources = [s for s in sources if s.stem in wanted]
        missing = wanted - {s.stem for s in sources}
        if missing:
            raise SystemExit(
                f"outline: unknown notebook(s): {', '.join(sorted(missing))}"
            )

    style = pick_style(args.color, None if args.output else sys.stdout)
    if args.groups:
        text = format_groups(sources, read_groups(args.groups), style)
    else:
        text = "\n\n".join(
            format_outline(source.stem, extract_items(source), style)
            for source in sources
        )
    text = text + "\n" if text else ""

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
