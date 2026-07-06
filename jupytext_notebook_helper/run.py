#!/usr/bin/env python3

"""Execute a percent notebook with internal imports *resolved* (inlined).

An intermediate testing mode, sitting between building the ``.ipynb`` and running
the raw ``.py`` directly:

* running the raw ``.py`` imports internal helpers from ``src/`` -- the whole
  module is importable, so a missing-dependency bug in the inlining is invisible;
* building the notebook inlines only a *subset* of each helper module.

This runner executes exactly that inlined subset, so a tree-shaking bug (a symbol
a copied function needs but that was not copied) surfaces here as a ``NameError``.

**Original-location tracking.** Every chunk of code is compiled against the file
it really came from: the notebook's own cells against the ``.py`` (offset to the
cell's line), and each inlined symbol against its ``src/`` module (offset to the
symbol's line), via ``compile(tree, real_path, ...)`` + ``ast.increment_lineno``.
Because the filenames are the real files and the line numbers are shifted to
match, tracebacks point at the true source location and ``linecache`` shows the
right lines -- no synthetic source maps needed.
"""

from __future__ import annotations

import argparse
import ast
import linecache
import logging
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import jupytext

from jupytext_notebook_helper.inlining import InternalResolver, find_imports

logger = logging.getLogger(__name__)

_SYNTHETIC_EXTERNAL = "<inlined-imports>"


def cell_start_lines(text: str) -> List[int]:
    """1-based line where each ``# %%`` cell's body starts, in order.

    jupytext delimits every cell (code or markdown) with a ``# %%`` marker, so
    this lines up one-to-one with the parsed cells.
    """
    starts: List[int] = []
    for i, line in enumerate(text.split("\n")):
        if line.startswith("# %%"):
            starts.append(i + 2)  # body starts on the line after the marker
    return starts


def _blank_magics(lines: List[str]) -> None:
    """Blank IPython magics / shell escapes in place (keeping line count)."""
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("%") or stripped.startswith("!"):
            lines[i] = ""


def _compile_exec(source: str, filename: str, lineno_offset: int, ns: dict) -> None:
    """Exec ``source`` as if it lived at ``filename`` starting at the offset.

    The line shift + real filename make any traceback point at the true source.
    """
    tree = ast.parse(source, filename=filename)
    if lineno_offset:
        ast.increment_lineno(tree, lineno_offset)
    # For synthetic origins (external imports gathered from library modules),
    # register the text so tracebacks can still show it; real files are read by
    # linecache directly.
    if not Path(filename).exists():
        linecache.cache[filename] = (
            len(source),
            None,
            source.splitlines(keepends=True),
            filename,
        )
    code = compile(tree, filename, "exec")
    exec(code, ns)  # noqa: S102 - executing notebook code is the whole point


def _exec_cell(
    source: str,
    filename: str,
    start_line: int,
    resolver: InternalResolver,
    ns: dict,
) -> None:
    lines = source.split("\n")
    _blank_magics(lines)

    try:
        parsed = find_imports("\n".join(lines))
    except SyntaxError:
        parsed = []

    # Resolve internal imports: their inlined blocks run first (definitions must
    # precede use), and the import lines are blanked out of the cell body.
    pre_exec: List[Tuple[str, str, int]] = []
    for imp in parsed:
        if not (imp.is_from and resolver.is_internal(imp.module, imp.level)):
            continue
        result = resolver.resolve(imp.module, imp.names)
        for block in result.blocks:
            pre_exec.append((block.source, block.origin.path, block.origin.lineno - 1))
        for ext in result.external:
            pre_exec.append((ext, _SYNTHETIC_EXTERNAL, 0))
        for ln in range(imp.lineno, imp.end_lineno + 1):
            lines[ln - 1] = ""

    for src, fname, offset in pre_exec:
        _compile_exec(src, fname, offset, ns)

    body = "\n".join(lines)
    if body.strip():
        _compile_exec(body, filename, start_line - 1, ns)


def run_notebook(
    source: str,
    src_root: str = "src",
    ns: Optional[dict] = None,
) -> Dict:
    """Execute ``source`` with internal imports inlined; return the namespace."""
    path = Path(source)
    text = path.read_text()
    document = jupytext.reads(text, fmt="py:percent")
    starts = cell_start_lines(text)
    resolver = InternalResolver(src_root=src_root)

    if ns is None:
        ns = {}
    ns.setdefault("__name__", "__main__")
    ns.setdefault("__file__", str(path))

    for idx, cell in enumerate(document["cells"]):
        if cell["cell_type"] != "code":
            continue
        start = starts[idx] if idx < len(starts) else 1
        _exec_cell(cell["source"], str(path), start, resolver, ns)

    return ns


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--debug", action="store_true", default=False, help="Log debug statements"
    )
    parser.add_argument(
        "--src-root",
        default="src",
        help="directory holding the internal library modules (default: src)",
    )
    parser.add_argument("source")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    try:
        run_notebook(args.source, src_root=args.src_root)
    except Exception as exc:
        # Drop the runner's own frames so the traceback starts at the notebook /
        # library code, at its real source location.
        tb = exc.__traceback__
        while tb is not None and tb.tb_frame.f_code.co_filename == __file__:
            tb = tb.tb_next
        traceback.print_exception(type(exc), exc, tb)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
