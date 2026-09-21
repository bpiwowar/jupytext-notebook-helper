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

## The header

The percent header's `jupyter.metadata` is where a source says what it is
called, for the index page and the manifest:

```python
# ---
# jupyter:
#   metadata:
#     practical_name: "Soft Actor-Critic"
#     practical_description: "Off-policy learning: TD3 plus an entropy bonus"
# ---
```

Both are optional: without a name the file name is used, title-cased, and
without a description the practical simply has none. Quote the values — a `: `
inside an unquoted YAML scalar is read as a mapping and loses the whole
header. The keys are configurable (`MANIFEST_NAME_KEY`,
`MANIFEST_DESCRIPTION_KEY`).

### What is handed out

The same place says whether the practical reaches the students at all, and
whether its corrigé goes with it:

```python
# ---
# jupyter:
#   metadata:
#     practical_name: "Soft Actor-Critic"
#     publish: no        # not handed out — still built for the teacher
#     solution: yes      # ... but its corrigé is released
# ---
```

| key | default | what it gates |
|-----|---------|---------------|
| `publish` | yes | the student notebooks, the bundle, `index.html`, the manifest, `rsync`, `publish-git` |
| `solution` | `PUBLISH_SOLUTIONS` | the corrigé of *this* practical: built by `make solution`, carried by `SOLUTION_ZIP`, listed and deployed |

`publish: no` holds a practical back without shelving it: the teacher
notebooks are still built and `make check` still runs it, so a practical you
are not handing out this year does not quietly stop working. A notebook that
was published before and is now held back is removed from the output
directories on the next `make student`, so `rsync --delete-excluded` takes it
off the server.

`PUBLISH_SOLUTIONS` (default `no`, see [Setting up a
course](course-setup.md#a-second-bundle-with-the-solutions)) is only what a
header that says nothing means. A header always wins, so one corrigé can go
out early (`solution: yes`) or stay back when the rest are released
(`solution: no`). An unpublished practical never releases a corrigé.

`make show-selection` prints the resulting lists.

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
  students at the work. Lines that should survive the blanking — scaffolding
  code, comments guiding the work — are marked as *hints*; see
  [Hints inside a `[[student]]` block](#hints-inside-a-student-block).
- `[[remove]] … [[/remove]]` — instructor-only content stripped from everything
  handed out.
- `[[assert]]`, `[[unindent]]`, and cell **tags** (`teacher`, `colab`,
  `not-colab`) gate content per variant.
- `# [[imports]]` — optional marker choosing where the gathered import block lands.
- `# [[keep-imports]]` — opt out of gathering for one cell, when its imports
  must run exactly where they are written.

Because the source is just Python, it lints, formats, and diffs like any other
file, and you never keep parallel copies in sync by hand.

## Hints inside a `[[student]]` block

Everything between `[[student]]` and `[[/student]]` is dropped from the student
notebook — *including ordinary comments*. A line only survives if it carries a
hint marker, `##` or `# >`: the marker is deleted and what follows is emitted at
that spot, at the original indentation.

```python
def cosine(a, b):
    # [[student]] Return the cosine similarity of two vectors
    ## # normalise both vectors first
    ## norm_a = ...
    # this plain comment is not handed out
    norm_a = np.linalg.norm(a)
    return a @ b / (norm_a * np.linalg.norm(b))
    # [[/student]]
```

The student gets:

```python
def cosine(a, b):
    # Return the cosine similarity of two vectors
    # normalise both vectors first
    norm_a = ...
    assert False, 'Not implemented yet'
```

`##` and `# >` are interchangeable; pick whichever reads better against your
formatter. What comes after the marker is emitted **raw**, so:

- **to leave code**, write the code: `## norm_a = ...`;
- **to leave a comment**, keep the `#`: `## # normalise both vectors first` (or
  `# ># normalise both vectors first`) — a bare `## normalise both vectors
  first` lands in the notebook as a syntax error;
- a marker on its own (`##`) emits a blank line, which is a cheap way to leave
  room to type in.

Two things to avoid: a hint must be on a **line of its own**, since the marker
is matched at its *last* occurrence on the line (`y = 1 ## z = 2` becomes
`y = 1 z = 2`, and `## a = 1 ## b = 2` becomes `## a = 1 b = 2`).

The teacher version keeps hint lines exactly as written, markers and all. The
`--solution` (*corrigé*) version drops them entirely and keeps the real body:
a hint is scaffolding for the student notebook, and next to the answer it would
at best duplicate a line (`norm_a = ...` above `norm_a = np.linalg.norm(a)`)
and at worst break the cell (`return ...` before the real `return`).

It opens the block with `# Solution`, carrying the instruction when there is
one, so a reader can tell the answer from the code that was given:

```python
def cosine(a, b):
    # Solution (Return the cosine similarity of two vectors)
    norm_a = np.linalg.norm(a)
    return a @ b / (norm_a * np.linalg.norm(b))
```

`[[assert]]` also lives inside the block: its text replaces `'Not implemented
yet'` in the assertion emitted at `[[/student]]`.

```python
    # [[student]] Return the cosine similarity of two vectors
    # [[assert]] cosine() is not implemented yet
```

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

**A Colab notebook is one file, with no checkout around it.** Whether it is
opened from Drive or from a public repository (`make publish-git`), nothing of
the course tree is next to it: a source must reach everything it needs through
the Hub or an absolute URL. `open("data/train.csv")`, `import resources`, a
path to `../outputs/` — each works locally and fails in Colab, and the install
cell cannot help. Writing under a relative path is fine: that is Colab's own
`/content`.
