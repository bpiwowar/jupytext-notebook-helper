#!/usr/bin/env python3

"""
Process percent notebooks

(1) Replace


```py3
# [[student]] Instructions
# [[assert]] Other assert instruction
...
# >hint = 2
# [[/student]]
```

by

```py3
# Instructions
assert False, "Not implemented yet"
hint = 2
```

(2) Removes [[remove]] ... [[/remove]] sections

(3) Inline images
"""

import argparse
import base64
import logging
import mimetypes
import re
import sys
from functools import partial
from pathlib import Path
from typing import List, Optional, Set, Union

import jupytext
import nbformat

from jupytext_notebook_helper.inlining import (
    Imports,
    InternalResolver,
    find_imports,
)

re_student_start = re.compile(
    r"""^(\s*)#(?:.*)\[\[STUDENT\]\]\s*(\S.*\S)?\s*$""", re.IGNORECASE
)
re_student_end = re.compile(r""".*\[\[/STUDENT\]\]""", re.IGNORECASE)
re_hint = re.compile(r"""(.*)(?:##(?:\s*)|# >)(\S.*|)$""", re.IGNORECASE)
re_assert = re.compile(r"""^(\s*)#(?:.*)\[\[assert\]\]\s*(\S.*)$""", re.IGNORECASE)

re_remove_start = re.compile(r""".*\[\[REMOVE\]\]""", re.IGNORECASE)
re_remove_end = re.compile(r""".*\[\[/REMOVE\]\]""", re.IGNORECASE)

re_unindent_start = re.compile(r"""(\s+)#.*\[\[unindent\]\]""", re.IGNORECASE)
re_unindent_end = re.compile(r"""(\s+)#.*\[\[/unindent\]\]""", re.IGNORECASE)

RE_MARKDOWN_IMAGE = re.compile(r"""!\[([^]]+)\]\(([^\)]+)\)""")
RE_MARKDOWN_INCLUDE = re.compile(r"""#include\s+(\S+)\s*$""")
RE_MARKDOWN_EXTENDS = re.compile(r"""#extends\s+(\S+)\s*$""")
RE_MARKDOWN_BLOCK = re.compile(r"""^(\s*)#block\s+(\S+)\s*$""")
RE_MARKDOWN_CONTENT = re.compile(r"""^(\s*)#content\s+(\S+)\s*$""")

# Match print_header("title") or print_header('title') at the start of a line
RE_PRINT_HEADER = re.compile(r"""^print_header\s*\(\s*["'](.+?)["']\s*\)\s*$""")

# Packages never emitted in a notebook's install cell, and packages always
# emitted (e.g. runtime-only deps such as sentencepiece that pip won't pull on
# its own). Course-agnostic defaults are empty; pass per-project values via the
# --pip-exclude / --pip-force-include CLI options.
PIP_EXCLUDE = set()
PIP_FORCE_INCLUDE = set()

# Directory containing uv.lock / pyproject.toml (for the `pip` install cell).
# Defaults to the current directory; override with --uv-root (e.g. when the
# build runs from a sub-directory).
UV_ROOT = "."

# Mapping from Python import names to pip package names
# (for cases where they differ)
IMPORT_TO_PACKAGE = {
    "PIL": "pillow",
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "google": "google-api-python-client",
    "OpenSSL": "pyopenssl",
    "Crypto": "pycryptodome",
}


def csv_list(string):
    return string.split(",")


def get_path(base_path: Path, path: Union[Path, str]):
    path = Path(path)
    if not path.is_file():
        path = base_path / path
    assert path.is_file(), f"Cannot find {path}"
    return path


def inline_image(matches, base_dir: Optional[Path] = None):
    title = matches[1]
    path = matches[2]
    if path.startswith("http:") or path.startswith("https:"):
        return matches[0]
    if path.startswith("data:"):
        encoded = path
    else:
        path = get_path(base_dir, path)

        mime_type, encoding = mimetypes.guess_type(path)
        image_b64 = (
            base64.encodebytes(path.read_bytes()).decode("ascii").replace("\n", "")
        )
        encoded = f"""data:{mime_type};base64,{image_b64}"""  # noqa: E231,E702

    return f"![{title}]({encoded})"


parser = argparse.ArgumentParser(
    description="Process Python (percent) notebooks to produce "
    "teacher/student / colab versions."
)
parser.add_argument(
    "--debug", action="store_true", default=False, help="Log debug statements"
)
parser.add_argument("--exclude", type=csv_list)
parser.add_argument("--include", type=csv_list)
parser.add_argument("--teacher", action="store_true", default=False)
parser.add_argument(
    "--solution",
    action="store_true",
    default=False,
    help="student-facing solution ('corrigé'): keep the solutions but strip all "
    "instructor debug info (cell-tag comments, [[student]]/[[remove]]/... markers, "
    "instructor-only [[remove]] blocks)",
)
parser.add_argument("--depdir", type=Path, default=None)
parser.add_argument(
    "--pip-exclude",
    type=csv_list,
    help="packages to never emit in the install cell (csv)",
)
parser.add_argument(
    "--pip-force-include",
    type=csv_list,
    help="packages to always emit in the install cell, e.g. runtime-only deps (csv)",
)
parser.add_argument(
    "--uv-root",
    default=".",
    help="directory containing uv.lock / pyproject.toml (default: current dir)",
)
parser.add_argument(
    "--src-root",
    default="src",
    help="directory holding the internal library modules that get inlined "
    "when imported (default: src)",
)
parser.add_argument("source", nargs="?")


args = parser.parse_args()
logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
exclude_tags = set(args.exclude or [])
included_tags = set(args.include or [])
PIP_EXCLUDE |= set(args.pip_exclude or [])
PIP_FORCE_INCLUDE |= set(args.pip_force_include or [])
UV_ROOT = args.uv_root or "."

# Resolves `from <internal> import ...` against src-root and inlines the needed
# symbols (with their transitive dependencies) instead of importing them.
resolver = InternalResolver(src_root=args.src_root)

# Old explicit-marker tags (`imports`, `copy`) are no longer needed: imports are
# now gathered from anywhere and internal imports inlined automatically. Warn
# once per tag if a source still uses them.
_deprecated_tags_warned: Set[str] = set()


def _warn_deprecated_tag(tag: str, message: str) -> None:
    if tag not in _deprecated_tags_warned:
        _deprecated_tags_warned.add(tag)
        logging.warning("the %r cell tag is no longer necessary: %s", tag, message)


teacher_mode = args.teacher
solution_mode = args.solution
assert not (teacher_mode and solution_mode), (
    "--teacher and --solution are mutually exclusive"
)

base_dir = Path(Path(args.source).parent if args.source else ".").resolve()
main_py = Path(args.source) if args.source else None

document = jupytext.read(
    open(args.source) if args.source else sys.stdin, fmt="py:percent"
)
deps: List[str] = []


def process_markdown(
    c_path: Path, text: str, lines: List[str], deps: List[str], lineno_start=0
):
    extends = []
    current = []
    current_block = None
    blocks = {}

    base_path = c_path.parent if c_path else base_dir

    logging.debug("Processing markdown %s", c_path.absolute())

    for lineno, line in enumerate(text.split("\n")):
        line = RE_MARKDOWN_IMAGE.sub(partial(inline_image, base_dir=base_path), line)

        # Processes "#extends ..."
        if match := RE_MARKDOWN_EXTENDS.match(line):
            # Extends
            assert lineno == 0, "#extends should be the first line"
            md_path = get_path(base_path, match.group(1))
            logging.debug("Extending %s", md_path)
            deps.append(str(md_path.resolve()))
            process_markdown(md_path, md_path.read_text(), extends, deps)

        # Processes "#include ..."
        elif match := RE_MARKDOWN_INCLUDE.match(line):
            md_path = get_path(base_path, match.group(1))
            logging.debug("Including %s", md_path)
            deps.append(str(md_path.resolve()))
            process_markdown(md_path, md_path.read_text(), current, deps)

        # Processes "#content ..."
        elif match := RE_MARKDOWN_CONTENT.match(line):
            blocks[match.group(2)] = current_block = []
        else:
            if extends:
                if current_block is not None:
                    current_block.append(line)
                elif line:
                    assert False, (
                        "#content has not been defined in "
                        f"{c_path}:{lineno + lineno_start + 1} / {line}"
                    )  # noqa: E226,E231
            else:
                current.append(line)

    if extends:
        unmatched = set(blocks.keys())
        for line in extends:
            if match := RE_MARKDOWN_BLOCK.match(line):
                spaces = match.group(1)
                key = match.group(2)
                logging.debug("[%s] extends key %s", c_path, key)
                lines.extend(f"{spaces}{line}" for line in blocks.get(key, []))
                try:
                    unmatched.remove(key)
                except KeyError:
                    pass
            else:
                lines.append(line)

        if unmatched:
            logging.warning(
                "In %s, %d contents have not been used: %s",
                c_path,
                len(unmatched),
                ", ".join(unmatched),
            )
    else:
        lines.extend(current)


def get_imported_packages(imports: Imports) -> set:
    """
    Get the set of package names based on collected imports.
    Maps import names to pip package names where they differ.
    """
    imported = set()

    # From "import X" statements
    for module in imports.imports.keys():
        top_level = module.split(".")[0]
        package = IMPORT_TO_PACKAGE.get(top_level, top_level)
        imported.add(package.lower())

    # From "from X import Y" statements
    for module in imports.imports_from.keys():
        top_level = module.split(".")[0]
        package = IMPORT_TO_PACKAGE.get(top_level, top_level)
        imported.add(package.lower())

    return imported


def get_all_transitive_deps(
    package: str, dependencies: dict, visited: set = None
) -> set:
    """
    Get all transitive dependencies of a package.
    """
    if visited is None:
        visited = set()

    if package in visited:
        return set()

    visited.add(package)
    result = set()

    for dep in dependencies.get(package, set()):
        result.add(dep)
        result.update(get_all_transitive_deps(dep, dependencies, visited))

    return result


def get_minimal_install_set(
    imported_packages: set,
    all_packages: dict,
    dependencies: dict,
    force_include: set = set(),
) -> set:
    """
    Given imported packages, find the minimal set of packages to install.

    1. Filter imports to only those that exist in the lock file
    2. Remove packages that are transitively implied by others
    """

    # Step 1: Keep only packages that exist in the lock file.
    # Match using PEP 503 normalization (case-insensitive, runs of -_. -> -) so that
    # e.g. the import `impact_index` resolves to the lock entry `impact-index`
    # without needing a hand-maintained mapping.
    def _norm(name):
        return re.sub(r"[-_.]+", "-", name).lower()

    norm_to_key = {_norm(k): k for k in all_packages}
    wanted = imported_packages | force_include
    packages_to_install = {
        norm_to_key[_norm(p)] for p in wanted if _norm(p) in norm_to_key
    }

    logging.info("Imported packages: %s", wanted)
    logging.info("Packages in lock file that are imported: %s", packages_to_install)

    # Step 2: Remove packages that are implied by others
    # A package is implied if another package in the set has it as a transitive dep
    minimal_set = set(packages_to_install)

    for pkg in packages_to_install:
        if pkg not in minimal_set:
            continue  # Already removed

        # Get all transitive deps of this package
        all_deps = get_all_transitive_deps(pkg, dependencies)

        # Remove any packages in our set that are covered by this package's deps
        for dep in all_deps:
            if dep in minimal_set and dep != pkg:
                logging.debug("Removing %s (implied by %s)", dep, pkg)
                minimal_set.discard(dep)

    # Always keep force-included packages, even if implied by another: these are
    # runtime-only deps (e.g. sentencepiece) that pip will not pull automatically.
    minimal_set |= {
        norm_to_key[_norm(p)] for p in force_include if _norm(p) in norm_to_key
    }

    return minimal_set


def _marker_excluded_ranges(source: str) -> set:
    """Line numbers (1-based) inside [[remove]]/[[student]] blocks.

    Imports there are left untouched (not moved to the shared imports cell), so
    e.g. a teacher-only import inside [[remove]] does not leak to students.
    """
    excluded = set()
    in_student = in_remove = False
    for i, line in enumerate(source.split("\n"), start=1):
        if re_remove_start.match(line):
            in_remove, _ = True, excluded.add(i)
            continue
        if re_remove_end.match(line):
            in_remove, _ = False, excluded.add(i)
            continue
        if re_student_start.match(line):
            in_student, _ = True, excluded.add(i)
            continue
        if re_student_end.match(line):
            in_student, _ = False, excluded.add(i)
            continue
        if in_student or in_remove:
            excluded.add(i)
    return excluded


def rewrite_cell_imports(source: str, imports: Imports) -> str:
    """Move external imports to the shared cell and inline internal ones.

    Top-level ``import``/``from`` statements are removed from the cell: external
    ones are recorded in ``imports`` (emitted later at the ``# [[imports]]``
    marker); ``from <internal> import ...`` statements are replaced in place by
    the requested symbols plus their transitive dependencies, with the external
    imports the inlined code needs folded back into ``imports``.
    """
    try:
        parsed = find_imports(source)
    except SyntaxError:
        # Cell is not valid Python on its own (e.g. contains a `%magic`); leave
        # its imports alone.
        return source
    if not parsed:
        return source

    excluded = _marker_excluded_ranges(source)
    lines = source.split("\n")
    plan = {}  # start lineno -> (end lineno, replacement lines)

    for imp in parsed:
        if any(ln in excluded for ln in range(imp.lineno, imp.end_lineno + 1)):
            continue

        if imp.is_from and resolver.is_internal(imp.module, imp.level):
            logging.info("Inlining internal import from %s", imp.module)
            result = resolver.resolve(imp.module, imp.names)
            for ext in result.external:
                imports.add(ext)
            block_text = "\n\n\n".join(block.source for block in result.blocks)
            plan[imp.lineno] = (
                imp.end_lineno,
                block_text.split("\n") if block_text else [],
            )
        else:
            imports.add(imp.source)
            plan[imp.lineno] = (imp.end_lineno, [])

    if not plan:
        return source

    out: List[str] = []
    i = 0
    while i < len(lines):
        lineno = i + 1
        if lineno in plan:
            end, replacement = plan[lineno]
            out.extend(replacement)
            i = end
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


#: `pip`-tagged cells, rendered after the whole document has been processed
pip_cells: List[dict] = []


def render_pip_cell(imports: Imports) -> str:
    """Render a `%pip install` cell from the (fully gathered) imports."""
    from jupytext_notebook_helper.uvutils import get_uv_versions

    uv_info = get_uv_versions(
        uv_lock_path=str(Path(UV_ROOT) / "uv.lock"),
        project_path=str(Path(UV_ROOT) / "pyproject.toml"),
    )

    # Get packages actually used based on imports
    imported_packages = get_imported_packages(imports)
    logging.debug("Imported packages: %s", imported_packages)

    # Get minimal set of packages to install (removing implied deps)
    minimal_packages = get_minimal_install_set(
        imported_packages,
        uv_info.all_packages,
        uv_info.dependencies,
        force_include=PIP_FORCE_INCLUDE,
    )
    logging.debug("Minimal packages to install: %s", minimal_packages)

    # Emit a package manifest reused downstream (e.g. to generate a
    # student-env pyproject from the union over all notebooks) instead of
    # re-parsing the sources.
    if args.depdir and args.source:
        pkgs_file = Path(args.depdir) / (Path(args.source).stem + ".pkgs")
        pkgs_file.parent.mkdir(parents=True, exist_ok=True)
        pkgs_file.write_text("\n".join(sorted(minimal_packages)) + "\n")

    source = "# Installing required packages\n\n"

    # Collect each group into a single `%pip install a==1 b==2 ...` invocation
    # rather than one line per package: faster (a single resolver pass) and
    # easier to read.
    build_specs = [
        f"{package}=={version}"
        for package, version in uv_info.build_packages.items()
        if package not in PIP_EXCLUDE
    ]
    if build_specs:
        source += "%pip install " + " ".join(build_specs) + "\n"
        source += "\n# Installing main packages\n\n"

    main_specs = [
        f"{package}=={version}"
        for package, version in uv_info.all_packages.items()
        # Extract base package name (without extras like [cuda])
        if package not in PIP_EXCLUDE
        and package.split("[")[0].lower() in minimal_packages
    ]
    if main_specs:
        source += "%pip install " + " ".join(main_specs) + "\n"

    return source


def process(  # noqa: C901
    path: Optional[Path], document, imports: Imports, hide_input=False
):
    cells = []

    # Process all cells (imports are gathered as we go, then emitted at the
    # `# [[imports]]` marker once the whole document has been processed).
    for ix, cell in enumerate(document["cells"]):
        lines: list[str | None] = []
        hide: int = 0
        remove = False
        unindent = 0
        student_space = None
        assert_ix: int | None = None

        tags = cell.get("metadata", {}).get("tags", [])
        cell_type = cell["cell_type"]

        # First, filters out
        if not any(tag in included_tags for tag in tags) and any(
            tag in exclude_tags for tag in tags
        ):
            continue

        if "imports" in tags:
            # Imports are now gathered from every cell automatically; the tag is
            # kept working (the cell is processed normally below) but redundant.
            _warn_deprecated_tag(
                "imports", "imports are now gathered from every cell automatically"
            )

        if "pip" in tags:
            assert cell["source"].strip() == "", "cells tagged with pip should be empty"
            # Rendering is deferred until the whole document has been processed,
            # so that the install cell covers the imports gathered from *every*
            # cell (including those pulled in by inlined internal modules),
            # wherever the pip cell is located in the notebook.
            pip_cells.append(cell)
            cells.append(cell)
            continue

        if "copy" in tags:
            # The `from <internal> import ...` lines in this cell are now inlined
            # by rewrite_cell_imports below; the whole-module copy is gone.
            _warn_deprecated_tag(
                "copy",
                "use `from <module> import <names>` and the module is inlined",
            )

        if cell_type == "markdown":
            process_markdown(path, cell["source"], lines, deps)
        else:
            cell["source"] = rewrite_cell_imports(cell["source"], imports)
            # In teacher mode, show cell tags as a comment
            logging.debug(
                "Cell %d: cell_type=%s, teacher_mode=%s, tags=%s, metadata=%s",
                ix,
                cell_type,
                teacher_mode,
                tags,
                cell.get("metadata", {}),
            )
            if teacher_mode and tags:
                lines.append(f"# tags: {tags}")

            for lineno, line in enumerate(cell["source"].split("\n")):
                # [[STUDENT]]
                if m := re_student_start.match(line):
                    student_space = m.group(1)
                    assert not hide, (
                        "Pas de [[/student]] correspondant à un [[student]] dans "
                        f"la cellule {ix + 1}: {cell['source'][:2]}"
                    )  # noqa: E226
                    hide = lineno + 1
                    if teacher_mode:
                        # Keep original line with markers in teacher mode
                        lines.append(line)
                    elif solution_mode:
                        # Solution kept below: show the instruction as a comment when
                        # there is one, but never leak a bare [[STUDENT]] placeholder.
                        if m.group(2):
                            lines.append(f"{student_space}# {m.group(2)}\n")
                    else:
                        # In student mode, show instructions as comment
                        lines.append(
                            f"{student_space}# "
                            f"{m.group(2) if m.group(2) else '[[STUDENT]]...'}\n"
                        )
                        assert_ix = len(lines)
                # [[/STUDENT]]
                elif re_student_end.match(line) is not None:
                    assert hide, (
                        f"Pas de [[student]] correspondant à un [[/student]] dans "
                        f"la cellule {ix + 1}: {cell['source'][:2]}"
                    )  # noqa: E226
                    if teacher_mode:
                        # lines.append(f"""{student_space}# assert False,
                        # 'Not implemented yet'\n""")
                        lines.append(line[unindent:])
                    elif solution_mode:
                        # Solution kept (appended below); just drop the marker.
                        pass
                    else:
                        lines.append(
                            f"""{student_space}assert False, 'Not implemented yet'\n"""
                        )
                    hide = False
                elif m := re_assert.match(line):
                    assert hide, "Pas de [[student]] pour un [[assert]]"
                    if teacher_mode:
                        # Keep original line with markers in teacher mode
                        lines.append(line)
                    elif solution_mode:
                        # Solution kept below; drop the [[assert]] instruction marker.
                        pass
                    else:
                        assert assert_ix is not None, (
                            f"[[assert]] en double line {lineno}"
                        )
                        lines[assert_ix] = None
                        assert_ix = None
                        lines.append(f"""{m.group(1)}{m.group(2)}\n"""[unindent:])

                elif re_remove_start.match(line):
                    assert not remove, "No [[/remove]] tag"
                    remove = True
                    if teacher_mode:
                        lines.append(line[unindent:])
                elif re_remove_end.match(line):
                    assert remove, "No [[remove]] tag for this [[/remove]]"
                    remove = False
                    if teacher_mode:
                        lines.append(line[unindent:])

                elif not teacher_mode and (m := re_unindent_start.match(line)):
                    assert not unindent, "No [[/unindent]] tag"
                    unindent = len(m.group(1))

                elif re_unindent_end.match(line) and not teacher_mode:
                    assert unindent, "No [[unindent]] tag for this [[/unindent]]"
                    unindent = 0

                elif hide and (not teacher_mode) and re_hint.match(line) is not None:
                    lines.append(re_hint.sub(r"\1\2", line[unindent:]))

                elif (
                    not (hide or remove)
                    or teacher_mode
                    # corrigé keeps the hidden solution body, but still drops
                    # instructor-only [[remove]] blocks.
                    or (solution_mode and not remove)
                ):
                    lines.append(line[unindent:])

        assert not hide, (
            "Pas de [[/student]] correspondant à un [[student]]"
            f" dans la cellule {ix + 1}: {cell['source'][:2]}"  # noqa: E226
        )
        assert not remove, (
            "Pas de [[/remove]] correspondant à un [[remove]]"
            f" dans la cellule {ix + 1}: {cell['source'][:2]}"  # noqa: E226
        )

        # Change source

        filtered_lines = list(filter(lambda line: line is not None, lines))

        first = next(
            (ix for ix, line in enumerate(filtered_lines) if line.strip() != ""), 0
        )
        last = (
            -next(
                (
                    ix
                    for ix, line in enumerate(filtered_lines[::-1])
                    if line.strip() != ""
                ),
                0,
            )
            or None
        )
        cell["source"] = "\n".join(filtered_lines[first:last])

        # Handle print_header() - convert to markdown header
        if cell_type == "code":
            source_lines = cell["source"].split("\n")
            header_titles = []
            new_source_lines = []
            found_non_header = False

            for line in source_lines:
                if m := RE_PRINT_HEADER.match(line):
                    if found_non_header:
                        raise ValueError(
                            f"print_header() must be at the beginning of a cell, "
                            f"found after other code in cell {ix + 1}"
                        )
                    header_titles.append(m.group(1))
                else:
                    # Comments and empty lines are OK before print_header
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        found_non_header = True
                    new_source_lines.append(line)

            if header_titles:
                # Create markdown header(s)
                header_md = "\n".join(f"### {title}" for title in header_titles)

                # Check if previous cell is markdown
                if cells and cells[-1]["cell_type"] == "markdown":
                    # Append to previous markdown cell
                    cells[-1]["source"] += "\n\n" + header_md
                else:
                    # Create new markdown cell using nbformat
                    md_cell = nbformat.v4.new_markdown_cell(source=header_md)
                    cells.append(md_cell)

                # Update code cell source (remove print_header lines)
                cell["source"] = "\n".join(new_source_lines).strip()

        # Remove outputs
        if "outputs" in cell:
            cell["outputs"] = []

        # Remove colab output
        if metadata := cell.get("metadata", None):
            if "colab" in metadata:
                del metadata["colab"]

        if cell["source"].strip() != "":
            cells.append(cell)

    # assert not(any(cell['source'].strip() == '' for cell in cells))
    document["cells"] = cells
    return document


# --- Process

imports = Imports()
document = process(main_py, document, imports)

# Inlined internal modules become build dependencies (so the Makefile rebuilds
# the notebook when a library module changes).
for resolved in resolver.resolved_paths:
    if resolved not in deps:
        deps.append(resolved)

for warning in imports.alias_warnings():
    logging.warning("import alias: %s", warning)

# Render the install cells now that every import (including those of inlined
# internal modules) has been gathered
for pip_cell in pip_cells:
    pip_cell["source"] = render_pip_cell(imports)

if not imports.empty():
    count = 0
    for cell in document["cells"]:
        source, count = re.subn(
            r"""^##?\s*\[\[imports\]\]""",
            imports.to_code(),
            cell.get("source", ""),
            flags=re.MULTILINE,
        )
        if count > 0:
            cell["source"] = source
            break

    if count == 0:
        # No explicit `# [[imports]]` marker: insert the gathered imports as a
        # new code cell right before the first code cell.
        insert_at = next(
            (i for i, c in enumerate(document["cells"]) if c["cell_type"] == "code"),
            len(document["cells"]),
        )
        import_cell = nbformat.v4.new_code_cell(source=imports.to_code().rstrip("\n"))
        document["cells"].insert(insert_at, import_cell)

jupytext.write(document, sys.stdout, fmt="ipynb")

if args.depdir is not None:
    assert args.source is not None

    source = Path(args.source).name

    target = source.replace(".py", ".d")
    target_s = "student/" + source.replace(".py", ".student.ipynb")
    target_t = "teacher/" + source.replace(".py", ".teacher.ipynb")
    with (args.depdir / target).open("wt") as fp:
        fp.write(f"""{target} {target_s} {target_t}: {" ".join(deps)}\n""")
