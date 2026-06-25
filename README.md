# jupytext-notebook-helper

Small runtime helpers for teaching notebooks written in the jupytext *percent*
format and built with `jupytext-filter` (student/teacher/colab versions).

Extracted from `master_mind.teaching.utils` so it can be reused across courses
without pulling in the whole master-mind framework.

```python
from jupytext_notebook_helper import *   # test_mode, skip_plots, print_header, is_notebook
```

- `test_mode` / `skip_plots` — driven by the `TESTING_MODE` env var
  (`off` | `on` | `full`).
- `print_header(title)` — formatted header when run as a script;
  jupytext-filter turns it into a markdown header in notebooks.
- On script execution (e.g. `make check`), `matplotlib.pyplot.show()` is patched
  to render figures inline in the terminal via `imgcat`.

Intended to be imported from a **teacher-only** cell: students never see the
test-mode machinery, and the package is not required on Colab.
