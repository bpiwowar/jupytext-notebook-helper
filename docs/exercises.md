[← README](../README.md)

# Exercise sheets (TD)

A practical can come with a **paper exercise sheet**: a warm-up done with a
pencil before the notebook, or a support the notebook refers to ("see exercise
2 of the sheet"). Sheets are written in [Typst](https://typst.app) and built by
the same `make` targets as the notebooks.

## Layout

```
exercises/
├── lib/td.typ        shared template (anything not at the top level is a dependency)
├── figures/…         images used by the sheets
├── indexing.typ      sheet of sources/indexing.py
└── evaluation.typ    sheet of sources/evaluation.py
```

A sheet is tied to the practical **of the same name**: it follows its
`publish:` / `solution:` header (see [Setting up a course](course-setup.md)).
A sheet without a practical is reported by `make check-exercises`.

| Output | Built by | Answers |
|---|---|---|
| `$(DESTDIR_TP)/exercises/<name>.pdf` | `student` | hidden |
| `$(TEACHER_DIR)/exercises/<name>.pdf` | `teacher` | shown |
| `$(SOLUTION_DIR)/exercises/<name>.pdf` | `solution` | shown |

`make exercises` builds the student and teacher sheets only; `make
check-exercises` (run by `check` when there are sheets) compiles them all.

## Showing or hiding the answers

Every sheet is compiled twice, with `--input solution=true` or `false`. The
sheet reads it from `sys.inputs`, typically in its template:

```typ
// exercises/lib/td.typ
#let solution-mode = sys.inputs.at("solution", default: "false") == "true"
#let solution(body) = if solution-mode {
  block(fill: luma(235), inset: 8pt, radius: 3pt, width: 100%, body)
}
```

```typ
// exercises/indexing.typ
#import "/lib/td.typ": *

= Exercise 1
Compute the idf of _house_.
#solution[$log(100 \/ 4) approx 3.22$]
```

Typst runs with `--root $(EXERCISES_DIR)`, so `/lib/td.typ` resolves to the
template wherever make runs from.

## Variables

| Variable | Default | |
|---|---|---|
| `EXERCISES_DIR` | `exercises` | where the `.typ` sheets are |
| `EXERCISES_SUBDIR` | `exercises` | sub-directory of each output directory |
| `TYPST` | `typst` | the compiler (e.g. `brew install typst`) |
| `TYPST_ARGS` | | extra arguments, e.g. `--font-path fonts` |
| `MANIFEST_EXERCISES_LABEL` | `Exercises (PDF)` | label in the manifest / index page |
| `MANIFEST_EXERCISES_SOLUTION_LABEL` | `Exercises — solution (PDF)` | label of the corrected sheet |

## In the manifest

A practical with a sheet lists it right after its notebooks, with
`"exercises": true`; the corrected sheet comes with the other solutions, and
only once the practical's corrigé is released:

```json
{ "label": "Exercises (PDF)", "path": "exercises/indexing.pdf", "exercises": true },
{ "label": "Exercises — solution (PDF)", "path": "solution/exercises/indexing.pdf",
  "exercises": true, "solution": true }
```

`make rsync` deploys the student sheets with the notebooks.
