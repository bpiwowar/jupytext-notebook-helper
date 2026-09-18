[← README](../README.md)

# The pipeline, end to end

What happens to a notebook from source to course page, step by step. Each step
has its own section in the [README](../README.md); this page puts them in order
and names the target for each.

```
 sources/tp1.py                          one percent-format file per TP
      │  make student / teacher / solution    (filter: markers, imports, inlining)
      ▼
 student/tp1.ipynb, student/colab/…      handed out
 teacher/tp1.ipynb, teacher/colab/…      kept (full solutions)
 student/solution/tp1.ipynb, …/colab/…   corrigé, released later
 student/tp-uv.zip, tp-uv-solution.zip   uv bundles (pyproject + uv.lock + notebooks)
      │  make check / run-teacher              does it run?
      │  make rsync                            DESTDIR_TP → SSH_HOST:SSH_PATH
      ▼
 $(SSH_PATH) on the server               what students download
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
# ---
```

In the cells, `[[student]] … [[/student]]` marks what students must write,
`[[remove]] … [[/remove]]` marks what only the instructor sees, and cell tags
(`teacher`, `colab`, `not-colab`) gate whole cells. See
[What you write](../README.md#what-you-write).

## 2. Build

| Target     | Produces |
|------------|----------|
| `student`  | `$(DESTDIR_TP)/<name>.ipynb`, `…/colab/<name>.ipynb`, `$(ZIP)` |
| `teacher`  | `$(TEACHER_DIR)/<name>.ipynb`, `…/colab/<name>.ipynb` |
| `solution` | `$(SOLUTION_DIR)/<name>.ipynb`, `…/colab/<name>.ipynb`, `$(SOLUTION_ZIP)` |
| `bundle`   | the zips only |

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
(default `colab/ *.ipynb *.zip`), plus `data/` when `RSYNC_DATA` is set.

The solutions are controlled by one switch, `PUBLISH_SOLUTIONS`:

- `no` (default): `rsync` excludes `SOLUTION_DIR` and `SOLUTION_ZIP`, and
  deletes any copy already on the server.
- `yes`: `rsync` builds `solution` first and uploads it.

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
