[← README](../README.md)

# The pipeline, end to end

What happens to a notebook from source to course page, step by step. Each step
has its own page (see the [README](../README.md#documentation)); this one puts
them in order and names the target for each.

```
 sources/tp1.py                          one percent-format file per TP
      │  make student / teacher / solution    (filter: markers, imports, inlining)
      ▼
 student/{local,colab}/tp1.ipynb         handed out
 teacher/{local,colab}/tp1.ipynb         kept (full solutions)
 solution/{local,colab}/tp1.ipynb        corrigé, released later
 student/tp-uv.zip, tp-uv-solution.zip   uv bundles (pyproject + uv.lock + notebooks)
 student/index.html                      the page that hands them out (INDEX_TITLE)
      │  make check / run-teacher              does it run?
      │  make rsync                            DESTDIR_TP → SSH_HOST:SSH_PATH
      │  make publish-git                      DESTDIR_TP → a public git repo
      ▼
 $(SSH_PATH) on the server               what students download
 github.com/owner/repo                   what students clone, and what Colab
      │                                        opens the colab/ notebooks from
      │  make manifest                         reads the headers only
      ▼
 practicals.json                         read by whatever announces the TP
                                         (slide-app's index page, a course site)
```

## 1. Write

One file per practical in `sources/`, in jupytext's percent format. The display
name comes from the header metadata (key `MANIFEST_NAME_KEY`, default
`practical_name`):

```python
# ---
# jupyter:
#   metadata:
#     practical_name: Affinage LoRA d'un décodeur
#     practical_description: Adapter un décodeur sur un corpus d'instructions
# ---
```

`practical_description` is a one-line summary; it is what the index page shows
next to the name, and it reaches the manifest as `description`.

In the cells, `[[student]] … [[/student]]` marks what students must write,
`[[remove]] … [[/remove]]` marks what only the instructor sees, and cell tags
(`teacher`, `colab`, `not-colab`) gate whole cells. See
[Writing a source](authoring.md#markers).

## 2. Build

| Target     | Produces |
|------------|----------|
| `student`  | `$(DESTDIR_TP)/{local,colab}/<name>.ipynb`, `$(ZIP)` |
| `teacher`  | `$(TEACHER_DIR)/{local,colab}/<name>.ipynb` |
| `solution` | `$(SOLUTION_DIR)/{local,colab}/<name>.ipynb`, `$(SOLUTION_ZIP)` |
| `bundle`   | the zips only |
| `index`    | `$(INDEX_HTML)`, the hand-out page — only with `INDEX_TITLE`; `student` does not build it |

The filter derives each variant from the same source. It gathers imports into a
single cell, inlines the course library functions a notebook uses, and adds a
pinned `%pip install` cell (generated from `uv.lock`) to the Colab variants.
Which packages that cell and the bundle carry is set in `pyproject.toml`,
under `[tool.jupytext-notebook-helper]`.

## 3. Check

| Target          | Runs |
|-----------------|------|
| `check`         | each source as a script, with the inlined code students get |
| `check-raw`     | each source as a plain script, faster and looser |
| `check-teacher` | the teacher notebooks through Jupyter, at profile `fast-test` |
| `run-teacher`   | the same at full size, keeping the executed notebooks in `run/` |
| `check-bundle`  | `uv` resolves the zip |

All but `check-bundle` also take a single notebook: `make check:<name>`.

## 4. Deploy

`make rsync` builds `student` and copies `$(DESTDIR_TP)/` to
`$(SSH_HOST):$(SSH_PATH)`. Only what `RSYNC_INCLUDE` matches is uploaded
(default `local/ colab/ *.ipynb *.zip *.html`), plus `data/` when `RSYNC_DATA`
is set.

The solutions are controlled by one switch, `PUBLISH_SOLUTIONS`:

- `no` (default): `rsync` excludes `SOLUTION_DIR` and `SOLUTION_ZIP`, and
  deletes any copy already on the server.
- `yes`: `rsync` builds `solution` first and uploads it.

## 4b. Publish to a public git repository

`make publish-git` mirrors the same tree into a clone of `GIT_PUBLISH_URL` and
commits it; `make publish-git-push` pushes. Two things the server cannot give:
a notebook Google Colab opens (it imports from GitHub, Drive or a gist only)
and one a student updates with `git pull`. `PUBLISH_SOLUTIONS` applies here
too — remembering that a git history keeps what it was once given.

## 4c. The page that hands them out

A directory of `.ipynb` files is not a hand-out: a student landing on
`$(SSH_PATH)` sees every notebook, the zip and the variant directories in
whatever order the server lists them. Setting `INDEX_TITLE` adds
`$(DESTDIR_TP)/index.html` — the archives to download first, then one row per
practical with its description and a link per variant.

`make index` writes it, and so do the two targets that publish it, `rsync` and
`publish-git`. `make student` does not: building the notebooks and handing them
out are separate steps. A course that wants the page rebuilt with every build
says so in one line of its `Makefile`:

```makefile
student: index
```

```makefile
INDEX_TITLE  := Reinforcement learning — practicals
INDEX_INTRO  := sources/index-intro.html   # a fragment, inserted verbatim
INDEX_FOOTER := Master MIND — Sorbonne Université
```

The page is built from the same description `make manifest` writes, so the
links cannot drift from what is deployed: `local/` and `colab/` paths relative
to the page, the Colab ones absolute when the course publishes to GitHub, and
the corrigé only once `PUBLISH_SOLUTIONS` says yes. It is one self-contained
file — inline CSS, no script, nothing dated — and it is only rewritten when its
content changes, so an unchanged course does not re-upload it.

## 5. Announce

`make manifest MANIFEST=<file>` writes a JSON description of the practicals:
ids, names, one entry per file, and the course-wide zips under `bundles`. It
reads only the source headers and builds no notebook, so it can run before
every build on the consumer side.

`baseUrl` gives the location of the notebooks relative to the consumer. Set it
with `MANIFEST_BASE_URL`, or have it derived from the two deploy paths with
`MANIFEST_RELATIVE_TO=<host>:<path where the consumer is deployed>`. With
`PUBLISH_SOLUTIONS=yes`, the manifest also lists the solution zip and each
practical's solution notebooks, flagged `"solution": true`.

When the course publishes to GitHub (step 4b), each Colab entry also carries an
absolute `url` into Colab, derived from `GIT_PUBLISH_URL`; the announcing page
uses it instead of `baseUrl + path`.

On the slide-app side, `make practical-manifest` calls this target, and
`practical.bundles` in `webpack.config.js` gives the wording of each zip (see
slide-app's `docs/practicals.md`).

## Releasing the solutions

After the session:

```bash
# Makefile: PUBLISH_SOLUTIONS := yes
make rsync                 # builds and uploads the solutions and their zip
```

Then redeploy whatever reads the manifest (for slide-app, `make deploy`,
which regenerates it), so the new links appear.

Nothing is listed or uploaded when the installed helper is older than 1.2.0,
which is the first version with `SOLUTION_ZIP` and `PUBLISH_SOLUTIONS`.
Check the version with `uv pip show jupytext-notebook-helper`.
