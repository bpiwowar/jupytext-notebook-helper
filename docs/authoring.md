[← README](../README.md)

# Writing a source

What goes into `sources/<name>.py`, and what the filter
(`python -m jupytext_notebook_helper.filter`) does with it.

## Editing

In VS Code, the
[Text as Notebook](https://marketplace.visualstudio.com/items?itemName=martinsoderstrom.vscode-text-as-notebook)
extension opens a percent file as a native notebook (right-click → *Text as
Notebook → Open as Notebook*, with the Jupyter extension installed for the
kernel). Cells run against a real kernel, and saving writes the plain `.py`
back: no paired `.ipynb`, nothing to keep in sync. Outputs are not kept, which
is what a source wants.

## Markers

An ordinary percent notebook, with a small marker vocabulary interpreted by the
filter (`python -m jupytext_notebook_helper.filter`):

```python
# %% [markdown]
# ## Exercise 1 — cosine similarity

# %%
import numpy as np

def cosine(a, b):
    # [[student]] Return the cosine similarity of two vectors
    return a @ b / (np.linalg.norm(a) * np.linalg.norm(b))
    # [[/student]]
```

- `[[student]] … [[/student]]` — kept verbatim in the teacher version; in the
  student version the body is replaced by the instruction (as a comment) and an
  `assert False, 'Not implemented yet'`, so the notebook still parses and points
  students at the work.
- `[[remove]] … [[/remove]]` — instructor-only content stripped from everything
  handed out.
- `[[assert]]`, `[[unindent]]`, and cell **tags** (`teacher`, `colab`,
  `not-colab`) gate content per variant.
- `# [[imports]]` — optional marker choosing where the gathered import block lands.
- `# [[keep-imports]]` — opt out of gathering for one cell, when its imports
  must run exactly where they are written.

Because the source is just Python, it lints, formats, and diffs like any other
file, and you never keep parallel copies in sync by hand.

## Imports in the build

The filter manages imports by *parsing* the source — no explicit `imports`/`copy`
cell tags are needed.

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

**`# [[keep-imports]]` opts a cell out of gathering.** Some cells have to import
at a precise point — typically to set up the environment before a heavy import
happens elsewhere. Mark such a cell and its imports stay exactly where you wrote
them:

```python
# %%
# [[keep-imports]]
# `transformers` refuses to start under Keras 3 unless TF is disabled *before*
# the first import — which happens in the gathered cell below.
import os

os.environ.setdefault("USE_TF", "0")
```

The marker line itself is dropped from every variant, and the packages the cell
imports are still pinned in the Colab install cell. Internal (`src/`) modules
are *not* inlined in such a cell — importing one there is reported as a warning,
since the generated notebook would no longer be self-contained.

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
`uv.lock`, to the minor series (`==x.y.*`). You only need an explicit
empty `pip`-tagged cell if you want the install cell somewhere other than the
top. Non-Colab builds (no `--colab`) get no install cell.
