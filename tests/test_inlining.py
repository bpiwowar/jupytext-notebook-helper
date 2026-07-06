"""Unit tests for the import-collection + internal-inlining core."""

import math
import textwrap

import pytest

from jupytext_notebook_helper.inlining import (
    Imports,
    InternalModule,
    InternalResolver,
    ResolveError,
    find_imports,
    render_module_inclusion,
)

# --------------------------------------------------------------------------- #
# Imports collector
# --------------------------------------------------------------------------- #


def test_imports_dedup_and_to_code():
    imp = Imports()
    imp.add("import numpy as np")
    imp.add("import numpy as np")  # duplicate -> collapsed
    imp.add("from torch import nn, optim")
    code = imp.to_code()
    assert code.count("import numpy as np") == 1
    assert "from torch import nn, optim" in code
    assert imp.alias_warnings() == []


def test_imports_conflicting_binding_raises():
    imp = Imports()
    imp.add("import numpy as np")
    with pytest.raises(ResolveError):
        imp.add("import torch as np")  # np bound to two different modules


def test_imports_alias_warning():
    imp = Imports()
    imp.add("import numpy as np")
    imp.add("import numpy")  # same module, second alias
    warnings = imp.alias_warnings()
    assert len(warnings) == 1
    assert "numpy" in warnings[0]


def test_imports_from_alias_warning():
    imp = Imports()
    imp.add("from torch import nn")
    imp.add("from torch import nn as neural")
    warnings = imp.alias_warnings()
    assert any("torch.nn" in w for w in warnings)


# --------------------------------------------------------------------------- #
# find_imports
# --------------------------------------------------------------------------- #


def test_find_imports_only_top_level():
    src = textwrap.dedent(
        """
        import os
        from a.b import c, d as e

        def f():
            import sys  # nested -> ignored
        """
    )
    imports = find_imports(src)
    assert len(imports) == 2
    assert imports[0].module is None and imports[0].names == [("os", "os")]
    assert imports[1].module == "a.b"
    assert imports[1].names == [("c", "c"), ("d", "e")]


# --------------------------------------------------------------------------- #
# InternalModule dependency tracking
# --------------------------------------------------------------------------- #


MODULE_SRC = textwrap.dedent(
    '''
    """A helper library module."""
    import numpy as np
    from .other import shared

    CONST = 10
    _UNUSED = "side effect"

    print("top-level side effect")   # must never be copied

    def _helper(x):
        return x + CONST

    def public(y):
        arr = np.asarray(y)
        return _helper(arr) + shared(arr)

    def unrelated():
        return 999

    class Widget(_BaseMixin):
        scale = CONST
        def render(self):
            return public(self.scale)

    class _BaseMixin:
        pass
    '''
)


def _module(tmp_path, dotted="mylib.helpers", src=MODULE_SRC):
    root = tmp_path / "src"
    path = root / (dotted.replace(".", "/") + ".py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src)
    return root, path


def test_internal_module_closure_transitive(tmp_path):
    _root, path = _module(tmp_path)
    mod = InternalModule("mylib.helpers", path)

    closure = mod.closure(["public"])
    # public -> _helper -> CONST, plus np and shared (import bindings)
    assert closure == {"public", "_helper", "CONST", "np", "shared"}


def test_internal_module_excludes_unrelated_and_side_effects(tmp_path):
    _root, path = _module(tmp_path)
    mod = InternalModule("mylib.helpers", path)
    closure = mod.closure(["public"])
    assert "unrelated" not in closure  # not referenced
    assert "_UNUSED" not in closure  # not referenced


def test_internal_module_class_base_and_body_deps(tmp_path):
    _root, path = _module(tmp_path)
    mod = InternalModule("mylib.helpers", path)
    closure = mod.closure(["Widget"])
    # Widget uses base class _BaseMixin (header), CONST (body) and public (method)
    assert {"_BaseMixin", "CONST", "public"}.issubset(closure)


def test_internal_module_missing_symbol(tmp_path):
    _root, path = _module(tmp_path)
    mod = InternalModule("mylib.helpers", path)
    with pytest.raises(ResolveError):
        mod.closure(["does_not_exist"])


def test_public_names_uses_dunder_all(tmp_path):
    src = textwrap.dedent(
        """
        __all__ = ["a"]
        def a(): pass
        def b(): pass
        """
    )
    _root, path = _module(tmp_path, src=src)
    mod = InternalModule("mylib.helpers", path)
    assert mod.public_names() == ["a"]


def test_public_names_heuristic_excludes_underscore(tmp_path):
    src = textwrap.dedent(
        """
        def a(): pass
        def _b(): pass
        C = 1
        """
    )
    _root, path = _module(tmp_path, src=src)
    mod = InternalModule("mylib.helpers", path)
    assert set(mod.public_names()) == {"a", "C"}


# --------------------------------------------------------------------------- #
# InternalResolver
# --------------------------------------------------------------------------- #


def _resolver_with(tmp_path, files):
    root = tmp_path / "src"
    for dotted, src in files.items():
        path = root / (dotted.replace(".", "/") + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(src))
    return InternalResolver(src_root=root)


def test_resolver_inlines_only_requested(tmp_path):
    resolver = _resolver_with(
        tmp_path,
        {
            "lib": """
                import numpy as np
                CONST = 3
                def used():
                    return np.zeros(CONST)
                def unused():
                    return 1
            """,
        },
    )
    result = resolver.resolve("lib", [("used", "used")])
    names = [b.name for b in result.blocks]
    assert "used" in names
    assert "CONST" in names
    assert "unused" not in names
    assert "import numpy as np" in result.external


def test_resolver_dedup_across_calls(tmp_path):
    resolver = _resolver_with(
        tmp_path,
        {"lib": "def a():\n    return 1\n"},
    )
    first = resolver.resolve("lib", [("a", "a")])
    second = resolver.resolve("lib", [("a", "a")])
    assert [b.name for b in first.blocks] == ["a"]
    assert second.blocks == []  # already emitted -> nothing new


def test_resolver_alias(tmp_path):
    resolver = _resolver_with(tmp_path, {"lib": "def foo():\n    return 1\n"})
    result = resolver.resolve("lib", [("foo", "bar")])
    sources = [b.source for b in result.blocks]
    assert any(s.strip().startswith("def foo") for s in sources)
    assert "bar = foo" in sources


def test_resolver_star_import(tmp_path):
    resolver = _resolver_with(
        tmp_path,
        {
            "lib": """
                def a(): return 1
                def _hidden(): return 2
                def b(): return _hidden()
            """,
        },
    )
    result = resolver.resolve("lib", [("*", "*")])
    names = {b.name for b in result.blocks}
    assert {"a", "b", "_hidden"}.issubset(names)  # _hidden pulled as dep of b


def test_resolver_nested_internal_module(tmp_path):
    resolver = _resolver_with(
        tmp_path,
        {
            "top": """
                from base import core
                def feature(x):
                    return core(x) + 1
            """,
            "base": """
                BASECONST = 7
                def core(x):
                    return x * BASECONST
            """,
        },
    )
    result = resolver.resolve("top", [("feature", "feature")])
    names = [b.name for b in result.blocks]
    # core + BASECONST inlined from the nested module, before feature
    assert "core" in names and "BASECONST" in names and "feature" in names
    assert names.index("core") < names.index("feature")
    assert result.external == []  # nothing external, all internal
    assert set(resolver.resolved_paths) >= {
        str(tmp_path / "src" / "top.py"),
        str(tmp_path / "src" / "base.py"),
    }


def test_resolver_bare_import_of_internal_module_errors(tmp_path):
    resolver = _resolver_with(
        tmp_path,
        {
            "top": """
                import base
                def feature():
                    return base.core()
            """,
            "base": "def core():\n    return 1\n",
        },
    )
    with pytest.raises(ResolveError):
        resolver.resolve("top", [("feature", "feature")])


def test_resolver_circular_import_detected(tmp_path):
    resolver = _resolver_with(
        tmp_path,
        {
            "a": "from b import bb\ndef aa():\n    return bb()\n",
            "b": "from a import aa\ndef bb():\n    return aa()\n",
        },
    )
    with pytest.raises(ResolveError):
        resolver.resolve("a", [("aa", "aa")])


def test_resolver_origins_point_at_source(tmp_path):
    resolver = _resolver_with(
        tmp_path,
        {
            "lib": """
                CONST = 1

                def target():
                    return CONST
            """,
        },
    )
    result = resolver.resolve("lib", [("target", "target")])
    target = next(b for b in result.blocks if b.name == "target")
    assert target.origin.path.endswith("lib.py")
    # `def target` is on line 4 of the dedented source (blank, CONST, blank, def)
    assert target.origin.lineno == 4


# --------------------------------------------------------------------------- #
# Full module inclusion (`import mylib.my.module`)
# --------------------------------------------------------------------------- #


def test_module_inclusion_builds_real_module(tmp_path):
    resolver = _resolver_with(
        tmp_path,
        {
            "mylib.my.module": """
                import math

                CONST = 3

                def area(r):
                    return CONST * math.pi * r
            """,
        },
    )
    inc = resolver.resolve_module_import("mylib.my.module")
    assert inc.bind_name == "mylib"
    assert [m.dotted for m in inc.modules] == ["mylib.my.module"]
    assert "import math" in inc.external

    code = render_module_inclusion(inc, "mylib.my.module", "mylib.my.module")
    ns = {}
    exec(code, ns)
    # dotted attribute access works, just like a normal import
    assert ns["mylib"].my.module.CONST == 3
    assert ns["mylib"].my.module.area(1) == pytest.approx(3 * math.pi)


def test_module_inclusion_nested_internal_deps_first(tmp_path):
    resolver = _resolver_with(
        tmp_path,
        {
            "top": """
                from base import core

                def feature(x):
                    return core(x) + 1
            """,
            "base": """
                BASE = 10

                def core(x):
                    return x * BASE
            """,
        },
    )
    inc = resolver.resolve_module_import("top")
    # dependency (base) is included before the module that needs it (top)
    assert [m.dotted for m in inc.modules] == ["base", "top"]

    code = render_module_inclusion(inc, "top", "top")
    ns = {}
    exec(code, ns)
    assert ns["top"].feature(3) == 31


def test_module_inclusion_alias_binds_leaf(tmp_path):
    resolver = _resolver_with(tmp_path, {"lib": "V = 5\n"})
    inc = resolver.resolve_module_import("lib")
    code = render_module_inclusion(inc, "lib", "L")
    ns = {}
    exec(code, ns)
    assert ns["L"].V == 5


def test_module_inclusion_dedup(tmp_path):
    resolver = _resolver_with(tmp_path, {"lib": "V = 1\n"})
    first = resolver.resolve_module_import("lib")
    second = resolver.resolve_module_import("lib")
    assert [m.dotted for m in first.modules] == ["lib"]
    assert second.modules == []  # already included


def test_module_inclusion_runs_side_effects(tmp_path):
    # Unlike `from lib import x`, a full `import lib` runs the whole module.
    resolver = _resolver_with(
        tmp_path,
        {"lib": "MARKER = []\nMARKER.append('ran')\n"},
    )
    inc = resolver.resolve_module_import("lib")
    ns = {}
    exec(render_module_inclusion(inc, "lib", "lib"), ns)
    assert ns["lib"].MARKER == ["ran"]


def test_annotation_only_dependencies_are_tracked(tmp_path):
    """Parameter/return annotations are evaluated eagerly (in the enclosing
    scope) before Python 3.14: a symbol used *only* in an annotation is still a
    dependency of the function."""
    from jupytext_notebook_helper.inlining import InternalResolver

    path = tmp_path / "src" / "lib.py"
    path.parent.mkdir(parents=True)
    path.write_text(
        textwrap.dedent(
            """
            from typing import Iterator, TypeVar

            T = TypeVar("T")

            def first(items: list[T]) -> Iterator[T]:
                yield items[0]
            """
        )
    )
    resolver = InternalResolver(src_root=tmp_path / "src")
    resolved = resolver.resolve("lib", [("first", "first")])
    sources = "\n".join(block.source for block in resolved.blocks)
    assert 'T = TypeVar("T")' in sources
