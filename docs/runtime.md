[← README](../README.md)

# Runtime helpers

Three questions a practical has to answer, and they are not the same question
— nor do they all belong to the same package:

| Question | Answered by | Set with | Lives in |
|---|---|---|---|
| What machine is this? | `hardware()` | detected; `NOTEBOOK_BACKEND` to force | [cs-lab](https://github.com/bpiwowar/cs-lab) |
| How much work should I do? | a `cs_lab.Profile` ladder | `NOTEBOOK_PROFILE` | [cs-lab](https://github.com/bpiwowar/cs-lab) |
| Where does output go? | `OutputMode` | `NOTEBOOK_OUTPUT` | here |

The first two are what the *notebook* needs, on the student's machine as much
as on yours, so they are `cs-lab`'s — a package with no hard dependencies that
a student installs alongside the course's own. The third is an *authoring*
concern: `print_header()` never survives into a built notebook (the filter
turns it into a markdown header), and under a kernel the output mode is always
`notebook`, so nothing here is patched.

```python
# %% tags=["teacher", "not-colab"]
from jupytext_notebook_helper import *      # print_header, figures in the terminal
from cs_lab import hardware
from mycourse.profiles import Profile

hw = hardware(Profile)
```

```python
# %%  (an ordinary cell — this is what students run too)
MODEL = Profile.pick(fast_test="tiny/model", low_gpu="big/model")
model = load_hf_model(MODEL, AutoModelForCausalLM, dtype=hw.dtype).to(hw.device)
```

`hardware()`, the `Profile` ladder and the in-notebook chooser are documented
in [cs-lab's README](https://github.com/bpiwowar/cs-lab#readme).

### Where output goes

`NOTEBOOK_OUTPUT` is `notebook` (figures inline), `console` (figures in the
terminal through `imgcat`, INFO logging — what `make check` wants) or `off` (no
figures at all: matplotlib pinned to `Agg`, `plt.show()` closes instead of
drawing). Unset, it follows the context: inline under a kernel, console
otherwise.

It is a **start-up** decision — matplotlib's backend cannot be swapped under a
running kernel — so `set_output_mode()` warns when a change cannot take effect
rather than pretending it did. For the same reason it stays out of the profile
chooser, which *can* be flipped mid-session; importing this package instead
adds an `images: shown|off` part to the note `hardware()` shows, so a teacher's
notebook says where both stand:

```
Profile: FAST_TEST — tiny budgets · images: off
```

- `print_header(title)` — a formatted header when run as a script;
  jupytext-filter turns it into a markdown header in notebooks.
