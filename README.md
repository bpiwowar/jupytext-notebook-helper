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
                         ┌─ student/  local/tp1.ipynb   (solutions blanked)
                         │            colab/tp1.ipynb   (+ auto %pip install cell)
   tp1.py   ──filter──▶  ├─ teacher/  local/tp1.ipynb   (solutions kept)
 (py:percent)            │            colab/tp1.ipynb
                         └─ solution/ local/tp1.ipynb   (optional corrigé)
                                      colab/tp1.ipynb
        │
        └─ + uv bundle (pyproject + uv.lock + notebooks) for a reproducible
             local install
```

Every output directory has the same two sub-directories, `local/` and `colab/`,
with the same file names, so a link only changes by one path segment.

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

`[[student]] … [[/student]]` is blanked in the student version (the instruction
becomes a comment followed by `assert False`), `[[remove]] … [[/remove]]` is
stripped from everything handed out, and cell tags gate content per variant.
The full vocabulary is in [Writing a source](https://github.com/bpiwowar/jupytext-notebook-helper/blob/main/docs/authoring.md).

Percent files open as notebooks in VS Code with the
[Text as Notebook](https://marketplace.visualstudio.com/items?itemName=martinsoderstrom.vscode-text-as-notebook)
extension (with the Jupyter extension for the kernel): cells run against a real
kernel, and the file on disk stays the plain `.py` source.

## What you get

Beyond the variant generation, the runtime helpers and build integrate a few
things that otherwise bite you late:

- **Imports are gathered automatically** from wherever you wrote them — put each
  `import` next to the code that needs it.
- **Internal library code is inlined** so a self-contained student notebook
  carries exactly the helper functions it uses — nothing more.
- **Colab gets a pinned `%pip install` cell** generated from `uv.lock`, so the
  first cell just works.
- **Everything is testable** at three fidelity levels (`make check` = resolved
  inlined subset, `make check-raw` = plain script, and the real notebook build),
  catching missing
  dependencies and broken cells before students do.

## Quick start

Include the shared make rules from the course's `Makefile`:

```makefile
ROOT := ..
include $(shell uv run python -m jupytext_notebook_helper.tpmk)
```

Then, from that directory:

```sh
make help       # every target, by section
make student    # student notebooks (local + Colab) and the uv bundle
make teacher    # teacher notebooks, with the solutions
make check      # run every source, with the code students get
```

## Documentation

| Page | Covers |
|------|--------|
| [The pipeline, end to end](https://github.com/bpiwowar/jupytext-notebook-helper/blob/main/docs/pipeline.md) | source → build → check → deploy → index page → manifest, with the target for each step |
| [Writing a source](https://github.com/bpiwowar/jupytext-notebook-helper/blob/main/docs/authoring.md) | markers, gathered imports, inlined library code, the Colab install cell |
| [Runtime helpers](https://github.com/bpiwowar/jupytext-notebook-helper/blob/main/docs/runtime.md) | `hardware()`, profiles, where output goes |
| [Checking and running](https://github.com/bpiwowar/jupytext-notebook-helper/blob/main/docs/testing.md) | `check`, `check-raw`, `lab`, `run-teacher`, `check-resources` |
| [Setting up a course](https://github.com/bpiwowar/jupytext-notebook-helper/blob/main/docs/course-setup.md) | the `Makefile`, `[tool.jupytext-notebook-helper]`, bundles, solutions, `rsync`, the index page |
| [Breaking changes](https://github.com/bpiwowar/jupytext-notebook-helper/blob/main/breaking.md) | what changed between major versions, and how to migrate |

The header of `jupytext_notebook_helper/tp.mk` lists every configurable
variable.
