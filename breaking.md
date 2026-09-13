# Breaking changes

This tracks breaking changes staged for a future major release. Nothing
listed here has shipped yet — every API below still works today, deprecated
ones with a `DeprecationWarning`. The point of this file is to let a
dependent course migrate ahead of time, on its own schedule, instead of
discovering the break at upgrade time.

**Until an entry below actually ships**, a course that still uses the old
API should pin `jupytext-notebook-helper<N.0.0` (the next major) rather than
a bare floor, so a routine upgrade cannot pull in the removal. Lift the
ceiling once migrated.

Each entry: what goes away, what replaces it, and the generic recipe for
moving from one to the other.

## `test_mode` / `TESTING_MODE`

- **Removed:** `test_mode` (the live proxy), `set_test_mode()`,
  `select_test_mode()`, `current_test_mode()`, `_auto_select()` and the
  widget it shows automatically on import, and the `TESTING_MODE` /
  `TESTING_MODE_WIDGET` environment variables.
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
  - Replace any direct read of the `TESTING_MODE` environment variable with
    `Profile.current()` (compute) or `current_output_mode()` /
    `skip_figures()` (figures) — don't re-derive from the old variable.
  - Replace `TESTING_MODE=...` / `TESTING_MODE_WIDGET=...` in Makefiles, CI,
    or notebook setup cells with `NOTEBOOK_PROFILE=...` /
    `NOTEBOOK_OUTPUT=...`.
  - Drop `from jupytext_notebook_helper import *` once nothing it exports
    (`test_mode`, `skip_plots`, …) is used anymore; import `hardware`,
    `print_header`, etc. by name instead.
