[← README](../README.md)

# Setting up a course

The project `Makefile`, the course metadata in `pyproject.toml`, the bundles and the deployment.

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
