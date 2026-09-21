# Breaking changes

This tracks breaking changes to this package, staged or shipped, so a
dependent course can migrate on its own schedule instead of discovering the
break at upgrade time. Each entry says its status:

- **Staged** — not released yet. The old API still works today (deprecated
  ones with a `DeprecationWarning`).
- **Shipped in `vX.0.0`** — already removed, starting with that tag.

**A course still on an entry's old API should pin
`jupytext-notebook-helper<X.0.0`** below that entry's major version (staged
or shipped) until it migrates, so a routine upgrade cannot pull in the
removal. Lift the ceiling once migrated.

Each entry: what goes away, what replaces it, and the generic recipe for
moving from one to the other.

## `test_mode` / `TESTING_MODE` — shipped in v1.0.0

- **Removed:** `test_mode` (the live proxy), `skip_plots`, `set_test_mode()`,
  `select_test_mode()`, `current_test_mode()`, `env_test_mode()`,
  `_auto_select()` and the widget it showed automatically on import, and the
  `TESTING_MODE` / `TESTING_MODE_WIDGET` / `SKIP_PLOTS` environment
  variables. `is_notebook()` survives, moved from `jupytext_notebook_helper.
  testmode` (deleted) to `jupytext_notebook_helper.notebook`.
- **Replaced by:** a `cached_hub.Profile` ladder for "how much work" (sizing
  datasets/models/steps), and `NOTEBOOK_OUTPUT` / `OutputMode` for "are
  figures drawn". `hardware(profiles)` ties the two together and, in a
  notebook, shows the active rung and figure-visibility as a single note.
- **Why:** `TESTING_MODE` conflated two independent axes (how much compute,
  whether to draw) into one on/off/full value, and offered only a fixed
  two-rung ladder. A `Profile` subclass lets a course define as many rungs as
  it needs, sized to its own hardware tiers.
- **Migration recipe:**
  - Define (or reuse) a `Profile` subclass for the course, with one rung per
    tier of work the notebooks actually need.
  - Replace `if test_mode: <small path> else: <full path>` with a check
    against the active rung, e.g. `if Profile.current() <= Profile.SOME_RUNG:
    ...`, or `hardware(Profile).pick(full_value, some_rung=small_value, ...)`
    where a single number/size is being chosen.
  - Replace any direct read of the `TESTING_MODE` / `SKIP_PLOTS` environment
    variables with `Profile.current()` (compute) or `current_output_mode()` /
    `skip_figures()` (figures) — don't re-derive from the old variables.
  - Replace `TESTING_MODE=...` / `TESTING_MODE_WIDGET=...` / `SKIP_PLOTS=...`
    in Makefiles, CI, or notebook setup cells with `NOTEBOOK_PROFILE=...` /
    `NOTEBOOK_OUTPUT=...`.
  - Drop `from jupytext_notebook_helper import *` once nothing it exports
    (`test_mode`, `skip_plots`, …) is used anymore; import `hardware`,
    `print_header`, etc. by name instead.

## Local notebooks at the root of each output directory — shipped in v2.0.0

- **Changes:** each output directory gets one sub-directory per variant, so
  local notebooks no longer share a directory with the Colab sub-directory,
  the bundles and the corrigé:

  ```
  now                                  v2.0.0
  $(DESTDIR_TP)/<name>.ipynb           $(DESTDIR_TP)/local/<name>.ipynb
  $(DESTDIR_TP)/colab/<name>.ipynb     $(DESTDIR_TP)/colab/<name>.ipynb
  $(TEACHER_DIR)/<name>.ipynb          $(TEACHER_DIR)/local/<name>.ipynb
  $(TEACHER_DIR)/colab/<name>.ipynb    $(TEACHER_DIR)/colab/<name>.ipynb
  $(SOLUTION_DIR)/<name>.ipynb         $(SOLUTION_DIR)/local/<name>.ipynb
  $(SOLUTION_DIR)/colab/<name>.ipynb   $(SOLUTION_DIR)/colab/<name>.ipynb
  ```

  The name of the new sub-directory is a variable (`LOCAL_SUBDIR`, default
  `local`), like `COLAB_SUBDIR`; it must not be empty either.
- **Why:** with local notebooks at the root, a listing of `$(DESTDIR_TP)`
  mixes notebooks, variant directories, zips and data; every variant being a
  directory makes the layout uniform and lets rsync and the manifest treat the
  variants the same way.
- **Migration recipe:**
  - Links to a local notebook (course pages, README, slides) gain one path
    segment: `<name>.ipynb` → `local/<name>.ipynb`. Links generated from the
    manifest need no change: `make manifest` writes the new paths.
  - A course-specific `RSYNC_INCLUDE` has to list `local/` alongside `colab/`
    (rsync does not descend into a directory it was not told to include).
  - `make clean` once, then rebuild: `clean` removes the notebooks left at
    the old paths, and `rsync --delete-excluded` takes them down from the
    server.

## Hints dropped from the corrigé — shipped in v2.4.0

- **Changes:** in `--solution` (*corrigé*) mode, hint lines inside a
  `[[student]]` block (`##` / `# >`) are no longer un-commented and emitted
  above the real body — they are dropped. Only the generated corrigé changes;
  no API, and the student and teacher versions are untouched.

  ```python
  # source                          corrigé, before        corrigé, now
  # [[student]]                     return ...             return q.argmax(1)
  ## return ...                     return q.argmax(1)
  return q.argmax(1)
  # [[/student]]
  ```
- **Why:** a hint is scaffolding for the student notebook. Next to the answer
  it duplicated a line at best, and at worst made the corrigé *not run* —
  `return ...` before the real `return` returns `Ellipsis`, and `summ += ...`
  raises `TypeError`. A corrigé that cannot be executed is not a corrigé.
- **Migration recipe:** rebuild (`make solution`). A block whose only content
  was hints — no solution line at all — now comes out empty, which is a syntax
  error: give it a body, or leave it as a `[[student]]`-only exercise with no
  corrigé line to show.
