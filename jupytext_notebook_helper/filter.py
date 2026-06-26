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
import ast
import base64
import logging
import mimetypes
import re
import sys
from functools import partial
from pathlib import Path
from typing import List, Optional, Union

import jupytext
import nbformat

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

RE_IMPORT_ALL = re.compile(r"""from ([\.\w]+) import .*(?:\s*#.*)$""")

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
parser.add_argument("source", nargs="?")


args = parser.parse_args()
logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)
exclude_tags = set(args.exclude or [])
included_tags = set(args.include or [])
PIP_EXCLUDE |= set(args.pip_exclude or [])
PIP_FORCE_INCLUDE |= set(args.pip_force_include or [])
UV_ROOT = args.uv_root or "."

teacher_mode = args.teacher

base_dir = Path(Path(args.source).parent if args.source else ".").resolve()
main_py = Path(args.source) if args.source else None

document = jupytext.read(
    open(args.source) if args.source else sys.stdin, fmt="py:percent"
)
deps: List[str] = []


class Imports:
    def __init__(self):
        #: Defined symbols (either module or module/symbol)
        self.symbols = {}
        self.imports_from = {}
        self.imports = {}

    def empty(self):
        return not self.imports and not self.imports_from

    @staticmethod
    def alias(name, alias):
        if name == alias:
            return name
        return f"{name} as {alias}"

    def to_code(self):
        s = ""
        for module, names in self.imports.items():
            for name in names:
                s += f"import {Imports.alias(module, name)}\n"
        for module, mapping in self.imports_from.items():
            s += f"from {module} import " + ", ".join(
                [Imports.alias(name, alias) for alias, name in mapping.items()]
            )
            s += "\n"

        return s

    def set(self, name: str, value):
        previous = self.symbols.get(name, None)
        if previous is None:
            self.symbols[name] = value
            return True
        elif previous != value:
            raise RuntimeError(f"Symbol mismatch: {name} / {previous} vs {value}")

        return False

    def add(self, source: str):
        for st in ast.parse(source).body:
            if isinstance(st, ast.Import):
                for symbol in st.names:
                    name = symbol.asname or symbol.name
                    if self.set(name, symbol.name):
                        self.imports.setdefault(symbol.name, []).append(name)

            elif isinstance(st, ast.ImportFrom):
                for symbol in st.names:
                    name = symbol.asname or symbol.name
                    if self.set(name, (st.module, symbol.name)):
                        self.imports_from.setdefault(st.module, {})[name] = symbol.name

            else:
                raise RuntimeError(
                    "(processing imports Cannot interpret %s [%s]", type(st)
                )


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


def process(  # noqa: C901
    path: Optional[Path], document, imports: Imports, hide_input=False
):
    cells = []

    # First pass: collect all imports from "imports" tagged cells
    for cell in document["cells"]:
        tags = cell.get("metadata", {}).get("tags", [])
        # Skip excluded cells
        if not any(tag in included_tags for tag in tags) and any(
            tag in exclude_tags for tag in tags
        ):
            continue
        if "imports" in tags:
            imports.add(cell["source"])

    # Second pass: process all cells
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
            # Already processed in first pass, skip
            continue

        if "pip" in tags:
            assert cell["source"].strip() == "", "cells tagged with pip should be empty"
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

            # Collect each group into a single `%pip install a==1 b==2 ...`
            # invocation rather than one line per package: faster (a single
            # resolver pass) and easier to read.
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

            cell["source"] = source
            cells.append(cell)
            continue

        if "copy" in tags:
            _hide_input = hide_input or ("hide-input" in tags)
            # Tags to propagate to imported cells
            propagate_tags = [t for t in tags if t not in ("copy", "hide-input")]

            for line in cell["source"].split("\n"):
                if m := RE_IMPORT_ALL.match(line):
                    logging.info("Processing import: %s", line)
                    module = m.group(1)
                    module_py = f"src/{module.replace('.', '/')}.py"

                    if module_py in deps:
                        continue

                    deps.append(module_py)
                    with (Path(module_py)).open("rt") as fp:
                        logging.info("Copying imported python file %s", module_py)
                        r = process(
                            Path(module_py),
                            jupytext.read(fp, fmt="py:percent"),
                            imports,
                            hide_input=hide_input,
                        )
                        for imported_cell in r["cells"]:
                            if imported_cell["source"].strip() != "":
                                imported_tags = imported_cell.get("metadata", {}).get(
                                    "tags", []
                                )

                                # Propagate tags from the copy cell
                                for ptag in propagate_tags:
                                    if ptag not in imported_tags:
                                        imported_cell.setdefault(
                                            "metadata", {}
                                        ).setdefault("tags", []).append(ptag)
                                        imported_tags = imported_cell["metadata"][
                                            "tags"
                                        ]

                                # In teacher mode, add tag comment for propagated tags
                                if (
                                    teacher_mode
                                    and propagate_tags
                                    and imported_cell["cell_type"] == "code"
                                ):
                                    imported_cell["source"] = (
                                        f"# tags: {imported_tags}\n"
                                        + imported_cell["source"]
                                    )

                                if _hide_input or ("hide-input" in imported_tags):
                                    if "hide-input" not in imported_tags:
                                        imported_cell.setdefault(
                                            "metadata", {}
                                        ).setdefault("tags", []).append("hide-input")

                                    # For jupyter
                                    imported_cell["metadata"].setdefault("jupyter", {})[
                                        "source_hidden"
                                    ] = True
                            cells.append(imported_cell)

            # Do not copy ourselves
            continue

        if cell_type == "markdown":
            process_markdown(path, cell["source"], lines, deps)
        else:
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

                elif not (hide or remove) or teacher_mode:
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

    assert count > 0, "No <# [[imports]]> found"

jupytext.write(document, sys.stdout, fmt="ipynb")

if args.depdir is not None:
    assert args.source is not None

    source = Path(args.source).name

    target = source.replace(".py", ".d")
    target_s = "student/" + source.replace(".py", ".student.ipynb")
    target_t = "teacher/" + source.replace(".py", ".teacher.ipynb")
    with (args.depdir / target).open("wt") as fp:
        fp.write(f"""{target} {target_s} {target_t}: {" ".join(deps)}\n""")
