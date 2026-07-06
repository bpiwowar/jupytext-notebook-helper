"""Import collection and internal-module inlining for teaching notebooks.

Two distinct jobs, both driven by parsing the Python source (no explicit
section markers required):

*External* imports (``numpy``, ``torch``, ...) are collected from anywhere in
the notebook and grouped into a single cell (see :class:`Imports`).

*Internal* imports -- ``from mylib.utils import foo, bar`` where
``src/mylib/utils.py`` exists -- are *inlined*: only the requested symbols and
their transitive dependencies are copied into the notebook, so unused (and
possibly side-effectful) top-level code from the library module is left behind.
Dependency tracking (:class:`InternalModule`) makes sure nothing a copied
symbol needs is missed.

Every inlined symbol keeps its :class:`Origin` (source file + line), which lets
the ``run`` testing mode point tracebacks back at the real library source.
"""

from __future__ import annotations

import ast
import logging
import symtable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

logger = logging.getLogger(__name__)


class ResolveError(RuntimeError):
    """Raised when an internal import cannot be resolved (missing symbol...)."""


def _start_lineno(node: ast.AST) -> int:
    """First source line of a node, *including* its decorators."""
    decorators = getattr(node, "decorator_list", None) or []
    return min([getattr(node, "lineno", 1)] + [d.lineno for d in decorators])


@dataclass
class Origin:
    """Where an inlined chunk of code came from."""

    path: str
    lineno: int  # 1-based line in ``path`` where the chunk starts


@dataclass
class ExtractedSymbol:
    """A single top-level definition (or alias line) copied out of a module."""

    name: str
    source: str
    origin: Origin


# --------------------------------------------------------------------------- #
# External imports collector
# --------------------------------------------------------------------------- #


class Imports:
    """Collect ``import`` / ``from ... import`` statements and re-emit them once.

    De-duplicates identical bindings, raises on a conflicting binding (the same
    name bound to two different things) and warns when a single module/symbol is
    pulled in under more than one alias.
    """

    def __init__(self):
        #: bound name -> module (for ``import``) or (module, symbol) (for ``from``)
        self.symbols: Dict[str, object] = {}
        #: module -> list of bound names (aliases)
        self.imports: Dict[str, List[str]] = {}
        #: module -> {alias: original symbol name}
        self.imports_from: Dict[str, Dict[str, str]] = {}
        #: module -> set of distinct aliases (for the >1-alias warning)
        self._module_aliases: Dict[str, Set[str]] = {}
        #: (module, symbol) -> set of distinct aliases
        self._symbol_aliases: Dict[Tuple[str, str], Set[str]] = {}

    def empty(self) -> bool:
        return not self.imports and not self.imports_from

    @staticmethod
    def alias(name: str, alias: str) -> str:
        if name == alias:
            return name
        return f"{name} as {alias}"

    def to_code(self) -> str:
        s = ""
        for module, names in self.imports.items():
            for name in names:
                s += f"import {Imports.alias(module, name)}\n"
        for module, mapping in self.imports_from.items():
            s += f"from {module} import " + ", ".join(
                Imports.alias(name, alias) for alias, name in mapping.items()
            )
            s += "\n"
        return s

    def set(self, name: str, value) -> bool:
        previous = self.symbols.get(name, None)
        if previous is None:
            self.symbols[name] = value
            return True
        elif previous != value:
            raise ResolveError(
                f"Import name {name!r} bound to two different things: "
                f"{previous!r} vs {value!r}"
            )
        return False

    def add(self, source: str) -> None:
        """Parse one or more import statements and record their bindings."""
        for st in ast.parse(source).body:
            if isinstance(st, ast.Import):
                for symbol in st.names:
                    name = symbol.asname or symbol.name
                    self._module_aliases.setdefault(symbol.name, set()).add(name)
                    if self.set(name, symbol.name):
                        self.imports.setdefault(symbol.name, []).append(name)
            elif isinstance(st, ast.ImportFrom):
                module = st.module or ""
                for symbol in st.names:
                    name = symbol.asname or symbol.name
                    self._symbol_aliases.setdefault((module, symbol.name), set()).add(
                        name
                    )
                    if self.set(name, (module, symbol.name)):
                        self.imports_from.setdefault(module, {})[name] = symbol.name
            else:
                raise ResolveError(f"Cannot interpret import statement: {ast.dump(st)}")

    def alias_warnings(self) -> List[str]:
        """Return a warning message for every import pulled in under >1 alias."""
        warnings: List[str] = []
        for module, aliases in self._module_aliases.items():
            if len(aliases) > 1:
                warnings.append(
                    f"module {module!r} imported under several aliases: "
                    + ", ".join(sorted(aliases))
                )
        for (module, symbol), aliases in self._symbol_aliases.items():
            if len(aliases) > 1:
                warnings.append(
                    f"{module}.{symbol} imported under several aliases: "
                    + ", ".join(sorted(aliases))
                )
        return warnings


# --------------------------------------------------------------------------- #
# Parsing import statements out of a cell / module
# --------------------------------------------------------------------------- #


@dataclass
class ParsedImport:
    lineno: int  # 1-based, inclusive
    end_lineno: int  # 1-based, inclusive
    is_from: bool
    module: Optional[str]  # None for bare ``import a, b``
    level: int  # relative-import dots (0 for absolute)
    names: List[Tuple[str, str]]  # list of (original, alias)
    source: str  # exact source text of the statement


def find_imports(source: str) -> List[ParsedImport]:
    """Return the *top-level* import statements in ``source`` (in order).

    Imports nested inside functions / conditionals are intentionally ignored:
    only module-level imports are collected / inlined.
    """
    tree = ast.parse(source)
    out: List[ParsedImport] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names = [(a.name, a.asname or a.name) for a in node.names]
            out.append(
                ParsedImport(
                    node.lineno,
                    node.end_lineno or node.lineno,
                    False,
                    None,
                    0,
                    names,
                    ast.get_source_segment(source, node) or "",
                )
            )
        elif isinstance(node, ast.ImportFrom):
            names = [(a.name, a.asname or a.name) for a in node.names]
            out.append(
                ParsedImport(
                    node.lineno,
                    node.end_lineno or node.lineno,
                    True,
                    node.module,
                    node.level,
                    names,
                    ast.get_source_segment(source, node) or "",
                )
            )
    return out


# --------------------------------------------------------------------------- #
# Internal module: dependency tracking + symbol extraction
# --------------------------------------------------------------------------- #


@dataclass
class _Stmt:
    """A top-level statement of an internal module."""

    index: int
    kind: str  # "def" | "import"
    source: str
    origin: Origin
    names: List[str] = field(default_factory=list)  # names it binds
    deps: Set[str] = field(default_factory=set)  # module-level names it references
    # import-only info:
    import_module: Optional[str] = None
    import_level: int = 0
    import_orig: Optional[str] = None  # original symbol name (from-import) or None
    import_alias: Optional[str] = None


@dataclass
class _Binding:
    name: str
    index: int
    deps: Set[str]


class InternalModule:
    """A ``src/`` module parsed for symbol-level extraction.

    Builds a dependency graph over the module's top-level bindings so that,
    given a set of requested names, we can copy exactly those plus everything
    they (transitively) need -- and nothing else.
    """

    def __init__(self, dotted: str, path: Union[str, Path]):
        self.dotted = dotted
        self.path = str(path)
        self.source = Path(path).read_text()
        self.tree = ast.parse(self.source, filename=self.path)
        self.stmts: List[_Stmt] = []
        self.bindings: Dict[str, _Binding] = {}
        self._all_names: Set[str] = set()
        self._dunder_all: Optional[List[str]] = None
        self._build()

    # -- construction ------------------------------------------------------- #

    def _build(self) -> None:
        # First pass: record bindings and statement records.
        pending: List[Tuple[_Stmt, ast.AST]] = []
        for node in self.tree.body:
            stmt = self._record(node)
            if stmt is not None:
                pending.append((stmt, node))
        self._all_names = set(self.bindings)

        # Second pass: compute dependencies now that all names are known.
        # Mutate ``stmt.deps`` in place so the _Binding sharing it stays in sync.
        globals_by_line = self._symtable_globals()
        for stmt, node in pending:
            if stmt.kind == "import":
                continue
            computed = self._deps_of(node, globals_by_line) & self._all_names
            for n in stmt.names:
                computed.discard(n)
            stmt.deps.clear()
            stmt.deps.update(computed)

    def _record(self, node: ast.AST) -> Optional[_Stmt]:
        origin = Origin(self.path, _start_lineno(node))
        idx = len(self.stmts)

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            stmt = _Stmt(idx, "def", self._segment(node), origin, [node.name])
            self._add_binding(node.name, stmt)
            self.stmts.append(stmt)
            return stmt

        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = self._assign_names(node)
            if not names:
                return None
            if "__all__" in names and isinstance(node, ast.Assign):
                self._dunder_all = self._literal_names(node.value)
            stmt = _Stmt(idx, "def", self._segment(node), origin, names)
            for n in names:
                self._add_binding(n, stmt)
            self.stmts.append(stmt)
            return stmt

        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name
                st = _Stmt(
                    len(self.stmts),
                    "import",
                    f"import {Imports.alias(alias.name, name)}",
                    origin,
                    [name],
                    import_module=alias.name,
                    import_level=0,
                    import_orig=None,
                    import_alias=name,
                )
                self._add_binding(name, st)
                self.stmts.append(st)
            return None

        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                name = alias.asname or alias.name
                st = _Stmt(
                    len(self.stmts),
                    "import",
                    "",  # rebuilt on demand
                    origin,
                    [name],
                    import_module=module,
                    import_level=node.level,
                    import_orig=alias.name,
                    import_alias=name,
                )
                self._add_binding(name, st)
                self.stmts.append(st)
            return None

        # Bare top-level statement (executable side effect): not a binding, and
        # deliberately *not* copied -- that is the whole point of inlining only
        # what is needed.
        return None

    def _add_binding(self, name: str, stmt: _Stmt) -> None:
        self.bindings[name] = _Binding(name, stmt.index, stmt.deps)

    def _segment(self, node: ast.AST) -> str:
        # `get_source_segment` starts at the `def`/`class` keyword; decorators
        # live on the lines above and must be part of the copied source.
        if getattr(node, "decorator_list", None):
            lines = self.source.split("\n")
            return "\n".join(lines[_start_lineno(node) - 1 : node.end_lineno])
        return ast.get_source_segment(self.source, node) or ""

    @staticmethod
    def _assign_names(node: Union[ast.Assign, ast.AnnAssign]) -> List[str]:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names: List[str] = []
        for target in targets:
            for sub in ast.walk(target):
                if isinstance(sub, ast.Name):
                    names.append(sub.id)
        return names

    @staticmethod
    def _literal_names(value: Optional[ast.AST]) -> Optional[List[str]]:
        if isinstance(value, (ast.List, ast.Tuple)):
            out = []
            for elt in value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    out.append(elt.value)
            return out
        return None

    # -- dependency analysis ------------------------------------------------ #

    def _symtable_globals(self) -> List[Tuple[int, int, Set[str]]]:
        """For each top-level function/class scope, the module-globals it uses.

        Returned as ``(start_line, scope_line, names)`` so a definition can claim
        every scope whose line falls inside it (this also folds in the separate
        ``__annotate__`` scopes Python creates for deferred annotations).
        """
        try:
            table = symtable.symtable(self.source, self.path, "exec")
        except SyntaxError:  # pragma: no cover - source already parsed above
            return []

        def scope_globals(scope: symtable.SymbolTable) -> Set[str]:
            names = {s.get_name() for s in scope.get_symbols() if s.is_global()}
            for child in scope.get_children():
                names |= scope_globals(child)
            return names

        return [
            (c.get_lineno(), c.get_lineno(), scope_globals(c))
            for c in table.get_children()
        ]

    def _deps_of(
        self, node: ast.AST, scope_globals: List[Tuple[int, int, Set[str]]]
    ) -> Set[str]:
        deps: Set[str] = set()

        # Body of functions/classes: free module-globals (via symtable), matched
        # by line range so nested + annotation scopes are attributed correctly.
        start = getattr(node, "lineno", 0)
        end = getattr(node, "end_lineno", start)
        for scope_line, _, names in scope_globals:
            if start <= scope_line <= end:
                deps |= names

        # Header parts evaluated in the *enclosing* (module) scope: decorators,
        # base classes, keyword bases, default argument values. symtable does not
        # attribute these to the child scope, so walk them directly.
        header_nodes: List[ast.AST] = list(getattr(node, "decorator_list", []) or [])
        if isinstance(node, ast.ClassDef):
            header_nodes += list(node.bases)
            header_nodes += [kw.value for kw in node.keywords]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            header_nodes += [d for d in a.defaults]
            header_nodes += [d for d in a.kw_defaults if d is not None]
            # Parameter / return annotations: evaluated eagerly in the
            # enclosing scope before Python 3.14 (no dedicated `__annotate__`
            # scope for symtable to report), so walk them explicitly. Under
            # 3.14 this double-counts harmlessly.
            args = [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]
            header_nodes += [
                arg.annotation
                for arg in args
                if arg is not None and arg.annotation is not None
            ]
            if node.returns is not None:
                header_nodes.append(node.returns)
        if isinstance(node, ast.AnnAssign) and node.annotation is not None:
            header_nodes.append(node.annotation)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            if node.value is not None:
                header_nodes.append(node.value)

        for hnode in header_nodes:
            for sub in ast.walk(hnode):
                if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                    deps.add(sub.id)
        return deps

    # -- queries ------------------------------------------------------------ #

    def public_names(self) -> List[str]:
        """Names exported by ``from module import *`` (``__all__`` or heuristics)."""
        if self._dunder_all is not None:
            return list(self._dunder_all)
        out = []
        for stmt in self.stmts:
            if stmt.kind == "def":
                for name in stmt.names:
                    if not name.startswith("_"):
                        out.append(name)
        return out

    def closure(self, requested: Sequence[str]) -> Set[str]:
        """All names needed to satisfy ``requested`` (transitive dependencies)."""
        needed: Set[str] = set()
        stack = list(requested)
        while stack:
            name = stack.pop()
            if name in needed:
                continue
            binding = self.bindings.get(name)
            if binding is None:
                raise ResolveError(
                    f"{self.dotted!r} ({self.path}) has no symbol {name!r}"
                )
            needed.add(name)
            stack.extend(binding.deps)
        return needed


# --------------------------------------------------------------------------- #
# Resolver: orchestrates inlining across the whole notebook
# --------------------------------------------------------------------------- #


def _reconstruct_import(stmt: "_Stmt") -> str:
    """Render a single-name import binding back to source."""
    if stmt.import_orig is None:
        return f"import {Imports.alias(stmt.import_module, stmt.import_alias)}"
    spec = Imports.alias(stmt.import_orig, stmt.import_alias)
    dots = "." * stmt.import_level
    return f"from {dots}{stmt.import_module or ''} import {spec}"


def _py_string_literal(text: str) -> str:
    """A triple-quoted literal whose value is ``text`` (line numbers preserved).

    No leading newline is added, so ``compile(<literal value>, ...)`` keeps the
    module's original line numbers. A trailing newline is ensured only to keep
    the closing quote off the last content line (and avoid a stray trailing ``"``).
    """
    body = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    if not body.endswith("\n"):
        body += "\n"
    return '"""' + body + '"""'


# Helper prelude embedded in every module-inclusion block. Self-contained so the
# cell works even when re-run in isolation. `exec(compile(src, path, ...))` uses
# the real source path, so tracebacks from the module body point at the true file.
_MODULE_LOADER = """\
import sys as _inline_sys
import types as _inline_types


def _inline_module(_name, _package, _path, _source):
    _module = _inline_sys.modules.get(_name)
    if _module is None:
        _module = _inline_types.ModuleType(_name)
        _inline_sys.modules[_name] = _module
    if _path:
        _module.__file__ = _path
    if _package:
        _module.__package__ = _package
    _parent = _name.rpartition(".")[0]
    if _parent:
        _inline_module(_parent, _parent.rpartition(".")[0], "", None)
        setattr(_inline_sys.modules[_parent], _name.rpartition(".")[2], _module)
    if _source is None:
        _module.__path__ = getattr(_module, "__path__", [])
    else:
        exec(compile(_source, _path, "exec"), _module.__dict__)
    return _module"""


def render_module_inclusion(inc: "ModuleInclusion", dotted: str, alias: str) -> str:
    """Render the code that builds ``dotted`` as a real, importable module object.

    ``import a.b.c`` binds ``a`` (dotted attribute access reaches ``a.b.c``);
    ``import a.b.c as x`` binds ``x`` to the ``a.b.c`` module.
    """
    lines = [_MODULE_LOADER, ""]
    for module in inc.modules:
        lines.append(
            f"_inline_module({module.dotted!r}, {module.package!r}, "
            f"{module.path!r}, {_py_string_literal(module.source)})"
        )
    if alias == dotted:
        top = dotted.split(".")[0]
        lines.append(f"{top} = _inline_sys.modules[{top!r}]")
    else:
        lines.append(f"{alias} = _inline_sys.modules[{dotted!r}]")
    return "\n".join(lines)


@dataclass
class ResolvedImport:
    blocks: List[ExtractedSymbol]  # new definitions to inline, in order
    external: List[str]  # external import statements the inlined code needs


@dataclass
class IncludedModule:
    """A whole internal module included as a real module object."""

    dotted: str
    package: str  # __package__ value ("" for a top-level module)
    source: str  # full module source
    path: str  # real file (for compile filename / tracebacks)


@dataclass
class ModuleInclusion:
    """Result of a full ``import <internal.module>`` inclusion.

    ``modules`` is in dependency order (a module's internal sub-imports come
    first); ``packages`` are the intermediate namespace packages that must exist
    for dotted attribute access; ``bind_name`` is the name bound in the notebook
    namespace (``mylib`` for ``import mylib.my.module``).
    """

    modules: List[IncludedModule]
    packages: List[str]
    bind_name: str
    external: List[str]

    def empty(self) -> bool:
        return not self.modules and not self.packages


class InternalResolver:
    """Decides which imports are internal and inlines them, with global dedup."""

    def __init__(self, src_root: Union[str, Path] = "src"):
        self.src_root = Path(src_root)
        self._modules: Dict[str, InternalModule] = {}
        #: (module_path, stmt_index) already emitted -- inline each symbol once
        self._emitted: Set[Tuple[str, int]] = set()
        #: alias assignment lines already emitted
        self._emitted_aliases: Set[Tuple[str, str]] = set()
        #: whole modules already included via `import <internal.module>`
        self._emitted_modules: Set[str] = set()
        #: resolved module files (for Makefile dependency tracking)
        self.resolved_paths: List[str] = []

    # -- module resolution -------------------------------------------------- #

    def _target(
        self, module: Optional[str], level: int, base: Optional[str]
    ) -> Optional[str]:
        """Resolve a (possibly relative) import to an absolute dotted module name."""
        if level == 0:
            return module
        if base is None:
            return None  # relative import outside a package context
        parts = base.split(".")
        if level > len(parts):
            return None
        prefix = parts[: len(parts) - level]
        if module:
            prefix = prefix + module.split(".")
        return ".".join(prefix)

    def module_path(self, dotted: str) -> Optional[Path]:
        path = self.src_root / (dotted.replace(".", "/") + ".py")
        return path if path.is_file() else None

    def is_internal(
        self, module: Optional[str], level: int = 0, base: Optional[str] = None
    ) -> bool:
        target = self._target(module, level, base)
        return bool(target) and self.module_path(target) is not None

    def get_module(self, dotted: str) -> InternalModule:
        module = self._modules.get(dotted)
        if module is None:
            path = self.module_path(dotted)
            if path is None:
                raise ResolveError(
                    f"No internal module {dotted!r} under {self.src_root}"
                )
            module = InternalModule(dotted, path)
            self._modules[dotted] = module
            self.resolved_paths.append(str(path))
        return module

    # -- resolution --------------------------------------------------------- #

    def resolve(
        self,
        dotted: str,
        requested: Sequence[Tuple[str, str]],
        _stack: Tuple[str, ...] = (),
    ) -> ResolvedImport:
        """Inline ``requested`` (list of ``(original, alias)``) from ``dotted``.

        Only symbols not yet emitted anywhere in this run are returned; the
        external imports the copied code relies on are surfaced separately.
        """
        if dotted in _stack:
            raise ResolveError(
                "Circular internal import: " + " -> ".join(_stack + (dotted,))
            )
        module = self.get_module(dotted)

        # Expand a "*" request into the module's public names.
        pairs: List[Tuple[str, str]] = []
        for orig, alias in requested:
            if orig == "*":
                pairs += [(n, n) for n in module.public_names()]
            else:
                pairs.append((orig, alias))

        needed = module.closure([orig for orig, _ in pairs])

        # Emit statements in source order; recurse into internal imports.
        indices = sorted({module.bindings[n].index for n in needed})
        pre_blocks: List[ExtractedSymbol] = []
        own_blocks: List[ExtractedSymbol] = []
        external: List[str] = []

        for idx in indices:
            stmt = module.stmts[idx]
            if stmt.kind == "import":
                self._handle_import(module, stmt, pre_blocks, external, _stack)
                continue
            key = (module.path, idx)
            if key in self._emitted:
                continue
            self._emitted.add(key)
            own_blocks.append(ExtractedSymbol(stmt.names[0], stmt.source, stmt.origin))

        # Alias lines for directly-requested renames (``import foo as f``).
        for orig, alias in pairs:
            if alias == orig:
                continue
            akey = (module.path, alias)
            if akey in self._emitted_aliases:
                continue
            self._emitted_aliases.add(akey)
            binding = module.bindings.get(orig)
            origin = (
                module.stmts[binding.index].origin
                if binding is not None
                else Origin(module.path, 1)
            )
            own_blocks.append(ExtractedSymbol(alias, f"{alias} = {orig}", origin))

        return ResolvedImport(pre_blocks + own_blocks, external)

    def _handle_import(
        self,
        module: InternalModule,
        stmt: _Stmt,
        pre_blocks: List[ExtractedSymbol],
        external: List[str],
        stack: Tuple[str, ...],
    ) -> None:
        target = self._target(stmt.import_module, stmt.import_level, module.dotted)

        # Internal dependency: recurse and inline it too.
        if target and self.module_path(target) is not None:
            if stmt.import_orig is None:
                raise ResolveError(
                    f"{module.dotted}: internal module {target!r} must be imported "
                    f"via `from {target} import ...`, not `import {target}`"
                )
            sub = self.resolve(
                target,
                [(stmt.import_orig, stmt.import_alias or stmt.import_orig)],
                stack + (module.dotted,),
            )
            pre_blocks.extend(sub.blocks)
            external.extend(sub.external)
            return

        # External dependency used by the inlined code: surface it for the
        # notebook's import cell.
        external.append(_reconstruct_import(stmt))

    # -- full module inclusion (`import mylib.my.module`) ------------------- #

    def resolve_module_import(
        self, dotted: str, _stack: Tuple[str, ...] = ()
    ) -> ModuleInclusion:
        """Include ``dotted`` (and any internal modules it imports) whole.

        Unlike :meth:`resolve`, this copies the *entire* module as a real module
        object so ``dotted``'s attributes stay reachable (``mylib.my.module.foo``)
        -- the faithful equivalent of ``import mylib.my.module``.
        """
        order: List[IncludedModule] = []
        external: List[str] = []
        packages: Set[str] = set()
        visited: Set[str] = set()

        def visit(name: str, stack: Tuple[str, ...]) -> None:
            if name in stack:
                raise ResolveError(
                    "Circular internal import: " + " -> ".join(stack + (name,))
                )
            if name in visited:
                return
            visited.add(name)
            module = self.get_module(name)

            # Every dotted ancestor is a namespace package we must create.
            parent = name.rpartition(".")[0]
            while parent:
                packages.add(parent)
                parent = parent.rpartition(".")[0]

            # Recurse into internal sub-imports (deps first); collect externals.
            for stmt in module.stmts:
                if stmt.kind != "import":
                    continue
                target = self._target(
                    stmt.import_module, stmt.import_level, module.dotted
                )
                if target and self.module_path(target) is not None:
                    visit(target, stack + (name,))
                else:
                    external.append(_reconstruct_import(stmt))

            if name not in self._emitted_modules:
                self._emitted_modules.add(name)
                order.append(
                    IncludedModule(
                        name, name.rpartition(".")[0], module.source, module.path
                    )
                )

        visit(dotted, _stack)

        # Only create packages that are not themselves one of the loaded modules
        # (a package that has a src file is loaded, not stubbed).
        loaded = {m.dotted for m in order} | self._emitted_modules
        pkgs = sorted(
            (p for p in packages if p not in loaded), key=lambda n: n.count(".")
        )
        return ModuleInclusion(order, pkgs, dotted.split(".")[0], external)
