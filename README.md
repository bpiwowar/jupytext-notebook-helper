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
                         ┌─ teacher/tp1.ipynb        (solutions kept)
   tp1.py   ──filter──▶  ├─ student/tp1.ipynb        (solutions blanked)
 (py:percent)            ├─ student/colab/tp1.ipynb  (+ auto %pip install cell)
                         └─ solution/tp1.ipynb       (optional corrigé)
        │
        └─ + uv bundle (pyproject + uv.lock + notebooks) for a reproducible
             local install
```

Each output directory keeps its Colab variants in a `colab/` sub-directory
(`teacher/colab/tp1.ipynb`, `solution/colab/tp1.ipynb`, …) — same file name as
the local notebook, so a link only changes by one path segment.

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
- `# [[keep-imports]]` — opt out of gathering for one cell, when its imports
  must run exactly where they are written.

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
from jupytext_notebook_helper import *   # test_mode, skip_plots, print_header,
                                         # is_notebook, set_test_mode, …
```

- `test_mode` / `skip_plots` — seeded by the `TESTING_MODE` env var
  (`off` | `on` | `full`): reduce datasets/training when testing, and drop every
  figure in `full`.
- `SKIP_PLOTS=1` (`1`/`true`/`yes`/`on`) — drop the figures **without** touching
  `test_mode`, for a full-size run whose log stays readable: each inline figure
  is a few hundred kB of base64.
- `print_header(title)` — a formatted header when run as a script;
  jupytext-filter turns it into a markdown header in notebooks.
- On script execution (e.g. `make check`), `matplotlib.pyplot.show()` is patched
  to render figures inline in the terminal via `imgcat` — unless `skip_plots`,
  which is now honoured before the inline rendering (until 0.5.0 `full` still
  wrote every figure to the terminal whenever `imgcat` was installed).

### Switching the mode from the notebook

`test_mode` is not a value captured at import but a **live proxy**: `if
test_mode:` asks for the current mode each time it runs. It still behaves like
the `bool` it replaces (`if`, `not`, `x if test_mode else y`,
`test_mode == True`, `int(test_mode)`, `f"{test_mode}"`); the only difference is
`test_mode is True`, which no course used.

- `set_test_mode("on" | "off" | "full")` — switch by hand, anywhere (also
  accepts `True` / `False`). Cells run *afterwards* see the new value; cells
  already executed of course keep the sizes they computed, so switch near the
  top, before the compute cells.
- `select_test_mode()` — display an `ipywidgets` toggle (`off` / `on`) in a
  notebook. It is called automatically when the package is imported from a
  notebook and `TESTING_MODE` is **not** set, so existing teacher notebooks get
  the chooser without any change; `TESTING_MODE_WIDGET=0` disables that
  automatic call, and an explicit call always displays it (useful if the cell
  was re-run, which clears its output).
- `current_test_mode()` — `"off"`, `"on"` or `"full"`.

What is *not* switchable at run time: **figure suppression**. `full` drops
figures by pinning matplotlib to `Agg` at import, and a notebook renders figures
through the inline backend at the end of each cell, not through the `plt.show()`
this package patches (that patch is script-only). So `full` stays a start-up
decision (`TESTING_MODE=full`, `SKIP_PLOTS=1`) — exactly how `make check` /
`make check-ipynb` use it. The in-notebook chooser therefore only offers
`off` / `on`, and `set_test_mode("full")` inside a notebook says that the
figures stay as they are instead of pretending otherwise.

`TESTING_MODE`, when set, gives the initial mode **and** suppresses the chooser:
a script run, `make check` and `make check-ipynb` behave exactly as before — no
widget, no prompt, no extra output, and nothing that ever waits for input
outside a notebook. It is not a lock: an explicit `set_test_mode(...)` from the
teacher still wins (a lock would defeat the point under `make lab-test`).

`ipywidgets` is an **optional** dependency
(`pip install "jupytext-notebook-helper[widgets]"`). Without it, the chooser
degrades to a one-line hint pointing at `set_test_mode(...)`.

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

### Interactively: `make lab` / `make lab-test`

`make lab` builds the teacher notebooks and opens JupyterLab on them;
`make lab-test` does the same with `TESTING_MODE=on` exported to the server, so
every kernel runs on reduced datasets/training **with plots still shown** (unlike
`check`, which uses `full` and disables them). Only the teacher variant carries
the `from jupytext_notebook_helper import *` cell, so this is the only build
where `test_mode` exists.

Since 0.8 `make lab` is usually enough: with no `TESTING_MODE` in the
environment, the helper cell shows a toggle and the mode can be switched from
the notebook itself (see *Switching the mode from the notebook*), so `lab-test`
is only useful to start **every** kernel of a session in `on` — and it then
suppresses the toggle. Override `LAB_DIR`, `LAB` or `LAB_TEST_MODE` to point
elsewhere (e.g. `make lab LAB_DIR=solution`).
Edits made in Lab are **not** written back to `sources/` — the notebooks are
build outputs.

## Wiring it into a course

Reusable make rules ship with the package. Include them from a project
`Makefile` after setting any project-specific variables:

```makefile
ZIP  := ../static/tp/tp-mycourse-uv.zip
ROOT := ..
include $(shell uv run python -m jupytext_notebook_helper.tpmk)
```

This generates the four variants per source plus a `uv` bundle
(`pyproject` + `uv.lock` + local notebooks + README), and an optional
`make solution` target for a student-facing corrigé:

```
sources/tp1.py  ->  $(DESTDIR_TP)/tp1.ipynb          student, local
                ->  $(DESTDIR_TP)/colab/tp1.ipynb    student, Colab
                ->  $(TEACHER_DIR)/tp1.ipynb         teacher, local
                ->  $(TEACHER_DIR)/colab/tp1.ipynb   teacher, Colab
                ->  $(SOLUTION_DIR)/tp1.ipynb        corrigé, local  (make solution)
                ->  $(SOLUTION_DIR)/colab/tp1.ipynb  corrigé, Colab  (make solution)
                 +  $(ZIP)                           uv bundle, local notebooks only
```

The sub-directory name is `COLAB_SUBDIR` (default `colab`); it must not be
empty. See the header of `jupytext_notebook_helper/tp.mk` for the full list of
configurable variables.

> **Upgrading from < 0.8.** The Colab notebooks used to be written next to the
> local ones as `<name>.colab.ipynb`. A course usually has nothing to change in
> its `Makefile`, but check three things:
>
> - `make clean` once after upgrading — it deletes the stale
>   `<name>.colab.ipynb` files, which would otherwise stay on disk (and keep
>   being deployed) forever;
> - a `.gitignore` listing `*.colab.ipynb` explicitly must gain the
>   `colab/` directories (a `.gitignore` that ignores `student/`, `teacher/`
>   and `solution/` wholesale needs nothing);
> - a deployment command that filters on file names — a typical
>   `rsync --include "*.ipynb" --exclude "*"` never descends into a directory
>   it has not been told to include, so it needs `--include "colab/"` as well.

### Course settings in `pyproject.toml`

Which packages the Colab install cell and the student environment carry is
course metadata rather than build layout, so it belongs with the course's other
metadata:

```toml
[tool.jupytext-notebook-helper]
# imported by no notebook, still needed at runtime
pip-force-include = ["sentencepiece", "torchvision"]
# never pip-installed by students (inlined, editable, or instructor-only)
pip-exclude = ["mycourse-internal"]
# added to the student environment whatever the notebooks import
student-base-deps = ["cached-hub>=0.3.0"]
student-env-name = "tp-mycourse"
student-requires-python = ">=3.10, <3.12"
```

The table is read from the `pyproject.toml` under `ROOT` (the `--uv-root` the
filter is given). Every key is optional and the matching make variable or
command-line option still works, adding to the list rather than replacing it.

The student environment is generated from the union of the per-notebook package
manifests plus that base, deduplicated **by project name, constrained
requirement first**: a notebook importing `cached_hub` contributes a bare
`cached-hub`, and `student-base-deps` is where a floor can be put on it —
without one, `uv lock` keeps whatever version it first resolved, which is how a
bundle ends up shipping a year-old release.

### Shipping an environment-only bundle

Two variables control what goes into `$(ZIP)`:

```makefile
BUNDLE_NOTEBOOKS := no                      # default: yes
BUNDLE_EXTRA     := src/mylib/resources.py  # extra files at the zip root
```

`BUNDLE_NOTEBOOKS=no` drops the `notebooks/` directory from the archive, so it
only carries the student `pyproject.toml` + `uv.lock` + `README.md` (+ whatever
`BUNDLE_EXTRA` lists). Students can then download it early to build the
environment and pre-download models/datasets — typically with a standalone
script shipped through `BUNDLE_EXTRA` — while the notebooks are still being
written and handed out separately.

The archive stays byte-stable across notebook edits: the generated student
`pyproject.toml` is only rewritten when the set of packages actually changes, so
the zip is rebuilt only when the environment changes, not on every build.
