# jupytext-notebook-helper

Small runtime helpers for teaching notebooks written in the jupytext *percent*
format and built with `jupytext-filter` (student/teacher/colab versions).

Extracted from `master_mind.teaching.utils` so it can be reused across courses
without pulling in the whole master-mind framework.

```python
from jupytext_notebook_helper import *   # test_mode, skip_plots, print_header, is_notebook
```

- `test_mode` / `skip_plots` — driven by the `TESTING_MODE` env var
  (`off` | `on` | `full`).
- `print_header(title)` — formatted header when run as a script;
  jupytext-filter turns it into a markdown header in notebooks.
- On script execution (e.g. `make check`), `matplotlib.pyplot.show()` is patched
  to render figures inline in the terminal via `imgcat`.

Intended to be imported from a **teacher-only** cell: students never see the
test-mode machinery, and the package is not required on Colab.

## Imports in the build

The filter (`python -m jupytext_notebook_helper.filter`) manages imports by
*parsing* the source — no explicit `imports`/`copy` cell tags are needed
anymore (they still work but warn that they are redundant).

**Imports can live anywhere; they are gathered automatically.** You no longer
have to keep imports in a dedicated cell (the old `imports`-tagged section):
put each `import` next to the code that first needs it, in any cell. Every
top-level import across all cells is collected, de-duplicated, and emitted in
one place — the cell containing the `# [[imports]]` marker if you add one (to
control where the block lands), otherwise a cell inserted just before the first
code cell. The original import lines are removed from wherever they appeared:

```python
# %% [markdown]
# ## Part 1

# %%
import numpy as np          # gathered — moved out of this cell
x = np.zeros(3)

# %% [markdown]
# ## Part 2

# %%
from collections import defaultdict   # gathered from here too
counts = defaultdict(int)
```

Both imports end up together in a single imports cell, while the cells above
keep only `x = np.zeros(3)` and `counts = defaultdict(int)`. Add a
`# [[imports]]` marker cell if you want to choose exactly where that block goes.

If the same module/symbol is pulled in under more than one alias, the build
logs a warning. Imports inside `[[remove]]` / `[[student]]` blocks are left in
place, so teacher-only imports never leak into the shared cell. Imports nested
inside a function or `if` are also left alone — only module-level (top-level)
imports are gathered.

**Internal library imports are inlined (with dependency tracking).** An import
whose module resolves to a file under `--src-root` (default `src/`) is treated
as *internal*: instead of importing it, the filter copies the requested symbols
straight into the notebook. Only what you ask for — plus its transitive
dependencies — is copied, so unused and side-effectful top-level code in the
library module is left behind:

```python
# src/mylib.py
import numpy as np
CONST = 3
def _scale(x): return x * CONST
def area(r):   return _scale(np.pi) * r
def unused():  ...            # never copied

# %% in the notebook
from mylib import area        # -> `CONST`, `_scale`, `area` inlined here;
                              #    `import numpy as np` added to the imports cell
```

Use targeted imports (`from mylib import area, plot`) instead of
`from mylib import *`; `*` still works and inlines every public symbol. Inlined
modules become Makefile build dependencies, so notebooks rebuild when a library
module changes.

**Whole-module inclusion for dotted use.** When you want to keep interacting
with a module by its dotted name, `import mylib.my.module` includes the **whole**
module as a real module object, so `mylib.my.module.foo()` keeps working exactly
like a normal import (no tree-shaking — the entire module, side effects and all,
travels with the notebook; any internal modules it imports come along too):

```python
# %% in the notebook
import mylib.my.module
mylib.my.module.foo()      # dotted access preserved
```

Use `from mylib.my.module import foo` when you only want `foo` (tree-shaken, no
side effects); use `import mylib.my.module` when you want the full module and
dotted interaction.

## Colab install cell

For the Colab variants (built with `--colab`), a `%pip install` cell is inserted
**automatically**, just before the first code cell — right ahead of the gathered
imports:

```
[ markdown intro ]
[ %pip install ... ]   ← auto-inserted for --colab
[ imports ]            ← auto-inserted (or the # [[imports]] marker)
[ first code cell ]
```

It pins the imported packages (and any pulled in by inlined modules) from
`uv.lock`, to the minor series (`==x.y.*`, see above). You only need an explicit
empty `pip`-tagged cell if you want the install cell somewhere other than the
top. Non-Colab builds (no `--colab`) get no install cell.

## Testing: three levels

- `make check` — runs each source **as a script**, importing internal helpers
  normally from `src/`. Fast, but because the whole module is importable it
  cannot reveal a *missing* inlined dependency.
- `make check-resolved` (`python -m jupytext_notebook_helper.run`) — runs each
  source with internal imports **resolved to the inlined subset**, i.e. exactly
  the code a student notebook will contain. A tree-shaking bug then surfaces as
  a `NameError` — reported at the **real** source location, because every chunk
  is compiled against the file it came from (notebook cell → `.py`; inlined
  symbol → its `src/` module).
- Building the notebook itself is the final level.

Both `check` and `check-resolved` accept a single source, e.g.
`make check-resolved:tp1-embeddings`, and record pass/fail (`make show-tests`
/ `make show-resolved`).
