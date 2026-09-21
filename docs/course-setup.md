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
sources/tp1.py  ->  $(DESTDIR_TP)/local/tp1.ipynb    student, local
                ->  $(DESTDIR_TP)/colab/tp1.ipynb    student, Colab
                ->  $(TEACHER_DIR)/local/tp1.ipynb   teacher, local
                ->  $(TEACHER_DIR)/colab/tp1.ipynb   teacher, Colab
                ->  $(SOLUTION_DIR)/local/tp1.ipynb  corrigé, local  (make solution)
                ->  $(SOLUTION_DIR)/colab/tp1.ipynb  corrigé, Colab  (make solution)
                 +  $(ZIP)                           uv bundle, local notebooks only
```

The sub-directory names are `LOCAL_SUBDIR` (default `local`) and
`COLAB_SUBDIR` (default `colab`); neither may be empty, and they must differ. See the header of `jupytext_notebook_helper/tp.mk` for the full list of
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
# installed, but without a version pin (see below)
pip-relax = ["numpy", "torch"]
# added to the student environment whatever the notebooks import
student-base-deps = ["cs-lab>=1.0"]
student-env-name = "tp-mycourse"
student-requires-python = ">=3.10, <3.12"
```

The table is read from the `pyproject.toml` under `ROOT` (the `--uv-root` the
filter is given). Every key is optional and the matching make variable or
command-line option still works, adding to the list rather than replacing it.

`pip-relax` (`--pip-relax`) is not `pip-exclude`: the package is still
installed and still listed in the student environment, it just loses its
`==x.y.*` pin in the Colab cell. Use it for what the hosted runtime
preinstalls and pins itself — pinning `numpy` or `torch` on Colab fights
`google-colab`'s own resolution, and a pin one minor behind what the runtime
ships triggers a full reinstall (for `torch`, gigabytes of CUDA wheels onto a
CPU runtime). The relaxed name is matched PEP 503-style against the base name,
so `numpy` also relaxes `gymnasium[mujoco]`-style entries by their base name,
and it applies to `[build-system] requires` too.

The student environment is generated from the union of the per-notebook package
manifests plus that base, deduplicated **by project name, constrained
requirement first**: a notebook importing `cs_lab` contributes a bare
`cs-lab`, and `student-base-deps` is where a floor can be put on it —
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

Solutions are usually handed out after the session, so `PUBLISH_SOLUTIONS`
(default `no`) says whether a practical releases its corrigé when its own
header does not. It concerns whatever of the solutions lives under
`$(DESTDIR_TP)`, the deployed directory:

```makefile
SOLUTION_DIR      := $(DESTDIR_TP)/solution          # a direct sub-directory
ZIP               := $(DESTDIR_TP)/tp-mycourse-uv.zip
SOLUTION_ZIP      := $(DESTDIR_TP)/tp-mycourse-uv-solution.zip
PUBLISH_SOLUTIONS := no                               # yes once released
```

- `make solution` builds the corrigés that are released, and `SOLUTION_ZIP`
  carries exactly those — an archive named after the solutions never holds one
  that is not out yet. Use `make teacher` to read a corrigé you have not
  released.
- `make rsync` excludes them (and `--delete-excluded` removes a copy that
  reached the server early); once something is released it builds `solution`
  and deploys it, whatever `RSYNC_INCLUDE` says.
- `make manifest` lists the archives under `$(DESTDIR_TP)` in `bundles`
  (`student`, and `solution` once released), and adds a practical's solution
  notebooks to its `files` — flagged `"solution": true` and labelled
  `MANIFEST_SOLUTION_LABEL` / `MANIFEST_SOLUTION_COLAB_LABEL` — as soon as
  that practical releases them.
- `make publish-git`, below, keeps them out of the public repository in the
  same way — with the difference that a git history is permanent: once pushed,
  a corrigé stays in it even if a later run takes it off the tip.

### Practical by practical

`PUBLISH_SOLUTIONS` is the course-wide *default*; each source overrides it in
its own header, which is also where a practical says whether it is handed out
at all (see [Writing a source](authoring.md#what-is-handed-out)):

```python
# ---
# jupyter:
#   metadata:
#     publish: no        # built for the teacher, checked, handed to nobody
#     solution: yes      # this corrigé is out, whatever PUBLISH_SOLUTIONS says
# ---
```

`make show-selection` prints what that adds up to: which practicals go out,
which of them with their corrigé, and which are held back.

## Deployment: `make rsync`

Setting `SSH_HOST` defines `rsync`, which builds `student` and copies
`$(DESTDIR_TP)/` to `$(SSH_HOST):$(SSH_PATH)`:

```makefile
SSH_HOST := user@example.org
SSH_PATH := public_html/mycourse/practical
RSYNC_DATA := ../data     # optional: symlinked into $(DESTDIR_TP) as `data`
```

`RSYNC_INCLUDE` (default `local/ colab/ *.ipynb *.zip *.html`) is what reaches the
server. The `local/` and `colab/` entries are not decoration: rsync never
descends into a directory it was not told to include, so without them the
notebooks silently stop being deployed. Bulk data (caches, corpora) travels separately, through `rsync-data`,
defined when `SSH_STUDENT_DATA` is set:

```makefile
STUDENT_DATA_DIR      := student-data
SSH_STUDENT_DATA      := ssh.example.org
SSH_STUDENT_DATA_PATH := student-data/cache
```

## The index page: `INDEX_TITLE`

What a student opens is a directory listing: every `.ipynb`, the zip and the
variant directories, in server order, with nothing saying which to take first.
Setting `INDEX_TITLE` replaces it with a page, `$(DESTDIR_TP)/index.html` —
the archives to download, then one row per practical with a link per variant:

```makefile
INDEX_TITLE  := Reinforcement learning — practicals
INDEX_INTRO  := sources/index-intro.html   # a fragment, inserted verbatim
INDEX_FOOTER := Master MIND — Sorbonne Université
INDEX_LANG   := en
# the archives' wording on the page; empty keeps "Notebooks and environment"
INDEX_STUDENT_LABEL  := Everything, as a uv project
INDEX_SOLUTION_LABEL := The corrigés
```

`make index` writes it, and `rsync` and `publish-git` — the targets that
publish it — build it first; `make student` does not, so building the notebooks
does not touch the page. Add `student: index` to the course's `Makefile` to
have it rebuilt with every build. It
is written from the same description `make manifest` produces — names and
descriptions from the source headers (`practical_name`,
`practical_description`), Colab links absolute when `GIT_PUBLISH_URL` is a
GitHub repository that carries the notebooks, and only the practicals and
corrigés that are actually released — so the page cannot list something the
deployment does not carry.

The page is one self-contained file: inline CSS (light and dark), no script,
no font to fetch, and nothing dated in it, so a build that changes nothing
leaves the file untouched and rsync has nothing to upload. Whatever the course
wants to say on top — which Python, where to ask for help, the schedule —
goes in the `INDEX_INTRO` fragment, which is inserted verbatim.

## Publishing to a public git repository: `make publish-git`

An `.ipynb` served over HTTPS is a file to download. Two things it cannot be:

- a notebook Google Colab opens — Colab imports from GitHub, from Drive or
  from a gist, and from nowhere else;
- something a student updates in place — a fixed typo means downloading the
  zip again.

Both follow from publishing the student tree to a public git repository.
Setting `GIT_PUBLISH_URL` defines two targets:

```makefile
GIT_PUBLISH_URL := git@github.com:owner/mycourse-lab.git
GIT_PUBLISH_DIR := outputs/git-publish     # the working clone; gitignore it
```

`make publish-git` builds the student notebooks, stages the tree and
**commits** it in a clone of that repository. `make publish-git-push` pushes,
and does nothing else. The split is the point: what reaches a public
repository is what the students read, so the step that makes it public is one
you take on purpose.

```console
$ make publish-git
$ git -C outputs/git-publish show --stat     # read it
$ make publish-git-push
```

The published tree mirrors `$(DESTDIR_TP)`:

```
README.md          $(GIT_PUBLISH_README), the bundle's README
pyproject.toml     $(BUNDLE_PYPROJECT) — a clone is a uv project: `uv sync`
uv.lock            $(BUNDLE_LOCK)
<BUNDLE_EXTRA>     the files the zip carries at its root
local/<name>.ipynb
colab/<name>.ipynb
solution/…         the corrigés that are released
```

`GIT_PUBLISH_ENV := no` leaves the environment out, publishing the notebooks
alone. `GIT_PUBLISH_NOTEBOOKS` does the converse and follows `BUNDLE_NOTEBOOKS`
by default: a course that hands the notebooks out one by one rather than in an
archive usually means it of this repository too. Set it to `yes` to publish an
env-only zip but a repository with the notebooks — which is what the absolute
Colab links need, since Colab opens a notebook from GitHub; without the
notebooks there, `make manifest` leaves those links relative rather than
pointing at files the repository does not carry. `GIT_PUBLISH_EXTRA` adds
files at the root.

What the mirror does *not* touch is `GIT_PUBLISH_PRESERVE` (default `.git
.gitignore .github LICENSE`): those belong to the published repository, not to
this build. Everything else there is the build's — a practical that is renamed
or deleted disappears from the repository on the next run.

The clone is kept between runs and `clean` leaves it alone, since it may hold
a commit that has not been pushed. For the same reason `publish-git` never
resets it: it fast-forwards onto `origin` when it can, and says so when it
cannot.

This is also where the Colab links of `make manifest` come from. When
`GIT_PUBLISH_URL` is a GitHub repository, each Colab entry of the manifest
gains an absolute `url`
(`https://colab.research.google.com/github/owner/repo/blob/main/colab/<id>.ipynb`)
next to its `path`, and the page that announces the practicals links *that*.
Nothing to configure: the paths line up because the published tree mirrors
`$(DESTDIR_TP)`, and a URL written out a second time is a URL that goes stale.
A repository elsewhere than GitHub keeps the entries relative and says why.
