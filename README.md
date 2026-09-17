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

Three questions a notebook has to answer, and they are not the same question:

| Question | Answered by | Set with |
|---|---|---|
| What machine is this? | `hardware()` | detected; `NOTEBOOK_BACKEND` to force |
| How much work should I do? | a `cached_hub.Profile` ladder | `NOTEBOOK_PROFILE` |
| Where does output go? | `OutputMode` | `NOTEBOOK_OUTPUT` |

```python
from jupytext_notebook_helper import hardware
from mycourse.profiles import Profile

hw = hardware(Profile)
MODEL = Profile.pick(fast_test="tiny/model", low_gpu="big/model")
model = load_hf_model(MODEL, AutoModelForCausalLM, dtype=hw.dtype).to(hw.device)
```

### `hardware()`

What the machine offers, and nothing about how hard to push it:

- `hw.device` / `hw.backend` (`cuda` | `mps` | `cpu`) / `hw.total_memory_gb`.
  **MPS counts as a GPU** — an Apple Silicon laptop with 128 GB of unified
  memory is not a machine without one.
- `hw.dtype` for inference (bf16 on CUDA, fp16 on MPS, fp32 on CPU) and
  `hw.train_dtype` for training (bf16 on CUDA, fp32 elsewhere — LoRA in pure
  fp16, without bf16's range, is unstable).
- `hw.has_bitsandbytes` / `hw.has_vllm` / `hw.has_flash_attention` /
  `hw.supports_bf16`: each is *the library imports* **and** *the backend
  supports it*. Gate a section on these rather than on `device.type == "cuda"`,
  which conflates "is this machine big" with "does this library exist here".
- `hw.synchronize()` / `hw.empty_cache()` / `hw.memory_used_gb()`, so a notebook
  stops writing the per-device branches by hand.
- `NOTEBOOK_BACKEND=cpu` forces a backend, to reproduce a CPU-only run.

`torch` is imported lazily: the build half of this package still works without
it.

### Where output goes

`NOTEBOOK_OUTPUT` is `notebook` (figures inline), `console` (figures in the
terminal through `imgcat`, INFO logging — what `make check` wants) or `off` (no
figures at all: matplotlib pinned to `Agg`, `plt.show()` closes instead of
drawing). Unset, it follows the context: inline under a kernel, console
otherwise.

It is a **start-up** decision — matplotlib's backend cannot be swapped under a
running kernel — so `set_output_mode()` warns when a change cannot take effect
rather than pretending it did.

- `print_header(title)` — a formatted header when run as a script;
  jupytext-filter turns it into a markdown header in notebooks.

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

Both run at `CHECK_PROFILE` (default `fast-test`, the smallest rung — it is
never auto-selected, so a check has to ask for it by name) with
`CHECK_OUTPUT=off`. Set `CHECK_TIMEOUT=<seconds>` to kill a source that runs
away, which turns a hung notebook into a `FAIL` instead of a stuck build:

```sh
make check CHECK_TIMEOUT=600
make check CHECK_PROFILE=low-gpu NOTEBOOK_ENV="HF_HUB_OFFLINE=1"
```

`NOTEBOOK_ENV` goes into the environment of every check recipe, so adding a
variable does not mean editing a rule.

### Interactively: `make lab` / `make lab-test`

`make lab` builds the teacher notebooks and opens JupyterLab on them;
`make lab-test` does the same with `NOTEBOOK_PROFILE=$(LAB_PROFILE)` exported to
the server, so every kernel starts on a reduced rung **with figures still
shown** (unlike `check`, which asks for the smallest rung and turns output off).

`make lab` is usually enough: with no `NOTEBOOK_PROFILE` in the environment the
ladder shows a chooser and the profile can be switched from the notebook itself,
so `lab-test` is only useful to pin **every** kernel of a session — and it then
suppresses the chooser. Override `LAB_DIR`, `LAB` or `LAB_PROFILE` to point
elsewhere (e.g. `make lab LAB_DIR=solution`).
Edits made in Lab are **not** written back to `sources/` — the notebooks are
build outputs.

## Running the teacher notebooks: `make run-teacher`

`check` runs the *sources*, as scripts, to say pass or fail. `run-teacher` runs
the built **teacher notebooks** through Jupyter and keeps the executed
notebooks, with their figures, under `$(RUN_DIR)` (default `run/`) — one `.log`
and one `.time` beside each. It is meant for a night on the best GPU around,
after which the results are read rather than only counted.

```sh
make run-teacher                        # every notebook, profile auto-detected
make run-teacher:03-efficiency          # just one
make run-teacher NOTEBOOK_PROFILE=small # a smaller rung
make run-teacher RUN_TIMEOUT=1200       # give up on a notebook after 20 min
make show-run                           # state, duration and path, per notebook
```

**What is not run again.** Each notebook has a stamp under `$(RUN_DIR)/.done/`,
named after the profile in force (`auto` when `NOTEBOOK_PROFILE` is unset), and
depending on `$(TEACHER_DIR)/<name>.ipynb` — which in turn depends on the
source. A notebook is therefore re-run when its source changed, when the profile
changed, or when the last run failed (a failure leaves no stamp), and skipped
otherwise. `make run-again` forgets every stamp without deleting the notebooks.

`make check-teacher` is the same runner used as a smoke test: profile
`$(RUN_CHECK_PROFILE)` (default `fast-test`) with `RUN_OUTPUT=off`, so it
answers "does everything still execute" rather than "is the figure right".
`check-teacher:<name>` for a single notebook.

Notebooks are executed **in place**, as a copy under `$(RUN_DIR)`, so the kernel
starts in the project directory where `src/` and the output directories are.
A cell that raises does not stop the run (`--allow-errors`): the error is found
afterwards in the saved notebook and in the missing stamp, so one broken cell
never throws away a night's work.

## Declared Hub resources: `make check-resources`

A course that declares the models and datasets its notebooks load — a
[`cached-hub`](https://github.com/bpiwowar/cached-hub) declaration module — gets
a `check-resources` target, and `check` depends on it, by pointing
`RESOURCES_PY` at that module:

```makefile
RESOURCES_PY := src/mycourse/resources.py
```

It runs two steps, because they catch different things. `cached-hub check` reads
the `load_hf_*` calls back out of `$(SOURCES_DIR)` and fails when the
declaration no longer describes them (a model added to a notebook, one that
stopped being loaded); it works on the AST, without importing, so a resource
built at run time is never executed by it. The second step imports the module
for real and builds every resource object — that is what catches an import
error, a typo in a factory argument, or a section that no longer loads. The
module path is derived from `RESOURCES_PY` and `SRC_ROOT`; override
`RESOURCES_MODULE` if the mapping is not the obvious one.

## Deployment: `make rsync`

Setting `SSH_HOST` defines `rsync`, which builds `student` and copies
`$(DESTDIR_TP)/` to `$(SSH_HOST):$(SSH_PATH)`:

```makefile
SSH_HOST := user@example.org
SSH_PATH := public_html/mycourse/practical
RSYNC_DATA := ../data     # optional: symlinked into $(DESTDIR_TP) as `data`
```

`RSYNC_INCLUDE` (default `colab/ *.ipynb *.zip`) is what reaches the server.
The `colab/` entry is not decoration: rsync never descends into a directory it
was not told to include, so without it the Colab notebooks silently stop being
deployed. Bulk data (caches, corpora) travels separately, through `rsync-data`,
defined when `SSH_STUDENT_DATA` is set:

```makefile
STUDENT_DATA_DIR      := student-data
SSH_STUDENT_DATA      := ssh.example.org
SSH_STUDENT_DATA_PATH := student-data/cache
```

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

`make help` (the default goal) lists every target, one section per kind of work:
build, check the sources, run the teacher notebooks, edit, deploy. A course adds
its own section — printed last — by defining and **exporting** `HELP_PROJECT`:

```makefile
define HELP_PROJECT
Corpus (this repository)
  lotte-corpus     build the LoTTE tarball
endef
export HELP_PROJECT
```

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

### A second bundle with the solutions

`SOLUTION_ZIP` adds an archive with the same environment and the corrigé
(`$(SOLUTION_DIR)`, local variants) in `notebooks/`, under the same file names
as the student ones. `make solution` and `make bundle` build it.

Solutions are usually handed out after the session, so their release is a
switch, `PUBLISH_SOLUTIONS` (default `no`). It concerns whatever of the
solutions lives under `$(DESTDIR_TP)`, the deployed directory:

```makefile
SOLUTION_DIR      := $(DESTDIR_TP)/solution          # a direct sub-directory
ZIP               := $(DESTDIR_TP)/tp-mycourse-uv.zip
SOLUTION_ZIP      := $(DESTDIR_TP)/tp-mycourse-uv-solution.zip
PUBLISH_SOLUTIONS := no                               # yes once released
```

- `make rsync` excludes them (and `--delete-excluded` removes a copy that
  reached the server early); with `yes` it builds `solution` and deploys them,
  whatever `RSYNC_INCLUDE` says.
- `make manifest` lists the archives under `$(DESTDIR_TP)` in `bundles`
  (`student`, and `solution` once released), and with `yes` adds each
  practical's solution notebooks to its `files`, flagged `"solution": true`
  and labelled `MANIFEST_SOLUTION_LABEL` / `MANIFEST_SOLUTION_COLAB_LABEL`.
