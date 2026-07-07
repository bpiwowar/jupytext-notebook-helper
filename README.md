# jupytext-notebook-helper

**Author your teaching notebooks once, in plain Python, and generate every
version you hand out — while a build that actually *runs* the code keeps you
honest.**

## Why

A single practical (*TP*) usually has to exist in several shapes at once:

- a **teacher** notebook with the full solutions,
- a **student** notebook where those solutions are blanked out,
- a **Colab** variant that installs its own dependencies,
- a **local** variant shipped with a pinned `uv` environment,
- optionally a **solution** hand-out (solutions kept, instructor scaffolding gone).

Maintaining those by hand means copy-pasting between notebooks, re-blanking
answers, chasing `pip install` lines, and discovering *in front of the class*
that a cell no longer runs. Notebooks are also miserable to diff and review in
git.

This project takes a different approach: **you write one source file per TP in
the jupytext *percent* format** — an ordinary, diffable, lintable `.py` file —
annotate it with a few lightweight markers, and a build step produces all the
variants above. The same build can *execute* each notebook (at three levels of
fidelity) so a broken example fails on your machine, not the student's.

## The idea in one picture

```
                         ┌─ teacher.ipynb        (solutions kept)
   tp1.py   ──filter──▶  ├─ tp1.ipynb            (solutions blanked)
 (py:percent)            ├─ tp1.colab.ipynb      (+ auto %pip install cell)
                         └─ solution.ipynb        (optional corrigé)
        │
        └─ + uv bundle (pyproject + uv.lock + notebooks) for a reproducible
             local install
```

You author in `tp1.py`; students never see the machinery.

## What you write

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

Because the source is just Python, it lints, formats, and diffs like any other
file, and you never keep parallel copies in sync by hand.

## What you get

Beyond the variant generation, the runtime helpers and build integrate a few
things that otherwise bite you late:

- **Imports are gathered automatically** from wherever you wrote them — put each
  `import` next to the code that needs it (see below).
- **Internal library code is inlined** so a self-contained student notebook
  carries exactly the helper functions it uses — nothing more.
- **Colab gets a pinned `%pip install` cell** generated from `uv.lock`, so the
  first cell just works.
- **Everything is testable** at three fidelity levels (`make check` = resolved
  inlined subset, `make check-raw` = plain script, and the real notebook build),
  catching missing
  dependencies and broken cells before students do.

## Runtime helpers

A tiny import surface, meant for a **teacher-only** cell — students never see the
test-mode machinery and the package is not required on Colab:

```python
from jupytext_notebook_helper import *   # test_mode, skip_plots, print_header, is_notebook
```

- `test_mode` / `skip_plots` — driven by the `TESTING_MODE` env var
  (`off` | `on` | `full`): reduce datasets/training when testing, and disable GUI
  plots in `full`.
- `print_header(title)` — a formatted header when run as a script;
  jupytext-filter turns it into a markdown header in notebooks.
- On script execution (e.g. `make check`), `matplotlib.pyplot.show()` is patched
  to render figures inline in the terminal via `imgcat`.

The package was extracted from `master_mind.teaching.utils` so it can be reused
across courses without pulling in the whole master-mind framework.

## Imports in the build

The filter manages imports by *parsing* the source — no explicit `imports`/`copy`
cell tags are needed anymore (they still work but warn that they are redundant).

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

- `make check` (the default; `python -m jupytext_notebook_helper.run`) — runs
  each source with internal imports **resolved to the inlined subset**, i.e.
  exactly the code a student notebook will contain. A tree-shaking bug (a symbol
  a copied helper needs, or a module-level side effect that was not inlined)
  surfaces as a `NameError` / runtime error — reported at the **real** source
  location, because every chunk is compiled against the file it came from
  (notebook cell → `.py`; inlined symbol → its `src/` module). This is the gate
  that matches the built notebooks, so it is the default.
- `make check-raw` — runs each source **as a plain script**, importing internal
  helpers normally from `src/`. Faster and looser; handy for early debugging,
  but because the whole module is importable it **cannot** reveal a missing
  inlined dependency (use `check` for that).
- Building the notebook itself is the final level.

Both accept a single source, e.g. `make check:tp1-embeddings` /
`make check-raw:tp1-embeddings`, and record pass/fail (`make show-tests` /
`make show-raw`).

## Wiring it into a course

Reusable make rules ship with the package. Include them from a project
`Makefile` after setting any project-specific variables:

```makefile
ZIP      := ../static/tp/tp-mycourse-uv.zip
PIP_ARGS := --uv-root .. --pip-force-include sentencepiece
include $(shell uv run python -m jupytext_notebook_helper.tpmk)
```

This generates the four variants per source plus a `uv` bundle
(`pyproject` + `uv.lock` + local notebooks + README), and an optional
`make solution` target for a student-facing corrigé. See the header of
`jupytext_notebook_helper/tp.mk` for the full list of configurable variables.
