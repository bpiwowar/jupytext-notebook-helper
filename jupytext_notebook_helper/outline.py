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

This reads the sources only: no notebook is built, so — like ``manifest`` —
it is cheap enough to run at any time, e.g. to review a practical's shape
before class or to spot a section with no work left for the student.
"""

from __future__ import annotations

import argparse
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

#: Header level synthesized for a `print_header(...)` call (matches the `###`
#: the filter turns it into — see `filter.RE_PRINT_HEADER`).
PRINT_HEADER_LEVEL = 3


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


def format_outline(name: str, items: list[Item]) -> str:
    """Render one source's outline as indented text."""
    headers = sum(1 for item in items if item.kind == "header")
    tasks = sum(1 for item in items if item.kind == "student")
    lines = [f"{name} ({headers} headers, {tasks} student tasks)"]

    current_level = 0  # depth of the last header seen, for un-headed sources
    for item in items:
        if item.kind == "header":
            current_level = item.level
            indent = "  " * (item.level - 1)
            lines.append(f"{indent}{'#' * item.level} {item.text}")
        elif item.kind == "student":
            indent = "  " * current_level
            lines.append(f"{indent}- [ ] {item.text}")
        else:  # "assert"
            indent = "  " * (current_level + 1)
            lines.append(f"{indent}assert: {item.text}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m jupytext_notebook_helper.outline",
        description="Print each source's header structure and student tasks",
    )
    parser.add_argument("--sources", type=Path, default=Path("sources"))
    parser.add_argument(
        "names", nargs="*", help="restrict to these notebooks (source stems)"
    )
    parser.add_argument("--output", type=Path, help="write to a file instead of stdout")
    args = parser.parse_args(argv)

    if not args.sources.is_dir():
        raise SystemExit(f"outline: no sources directory at {args.sources}")

    sources = sorted(args.sources.glob("*.py"))
    if args.names:
        wanted = set(args.names)
        sources = [s for s in sources if s.stem in wanted]
        missing = wanted - {s.stem for s in sources}
        if missing:
            raise SystemExit(
                f"outline: unknown notebook(s): {', '.join(sorted(missing))}"
            )

    text = "\n\n".join(
        format_outline(source.stem, extract_items(source)) for source in sources
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
