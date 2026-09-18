[← README](../README.md)

# Checking and running the notebooks

From a quick pass/fail over the sources to a full run of the teacher notebooks.

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
depending on `$(TEACHER_DIR)/local/<name>.ipynb` — which in turn depends on the
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
