[← README](../README.md)

# Runtime helpers

What a notebook imports from this package at run time. `torch` is optional: the build half works without it.

Three questions a notebook has to answer, and they are not the same question:

| Question | Answered by | Set with |
|---|---|---|
| What machine is this? | `hardware()` | detected; `NOTEBOOK_BACKEND` to force |
| How much work should I do? | a `cached_hub.Profile` ladder | `NOTEBOOK_PROFILE` |
| Where does output go? | `OutputMode` | `NOTEBOOK_OUTPUT` |

```python
from jupytext_notebook_helper import hardware
from mycourse.profiles import Profile

hw = hardware(Profile)
MODEL = Profile.pick(fast_test="tiny/model", low_gpu="big/model")
model = load_hf_model(MODEL, AutoModelForCausalLM, dtype=hw.dtype).to(hw.device)
```

### `hardware()`

What the machine offers, and nothing about how hard to push it:

- `hw.device` / `hw.backend` (`cuda` | `mps` | `cpu`) / `hw.total_memory_gb`.
  **MPS counts as a GPU** — an Apple Silicon laptop with 128 GB of unified
  memory is not a machine without one.
- `hw.dtype` for inference (bf16 on CUDA, fp16 on MPS, fp32 on CPU) and
  `hw.train_dtype` for training (bf16 on CUDA, fp32 elsewhere — LoRA in pure
  fp16, without bf16's range, is unstable).
- `hw.has_bitsandbytes` / `hw.has_vllm` / `hw.has_flash_attention` /
  `hw.supports_bf16`: each is *the library imports* **and** *the backend
  supports it*. Gate a section on these rather than on `device.type == "cuda"`,
  which conflates "is this machine big" with "does this library exist here".
- `hw.synchronize()` / `hw.empty_cache()` / `hw.memory_used_gb()`, so a notebook
  stops writing the per-device branches by hand.
- `NOTEBOOK_BACKEND=cpu` forces a backend, to reproduce a CPU-only run.

`torch` is imported lazily: the build half of this package still works without
it.

### Where output goes

`NOTEBOOK_OUTPUT` is `notebook` (figures inline), `console` (figures in the
terminal through `imgcat`, INFO logging — what `make check` wants) or `off` (no
figures at all: matplotlib pinned to `Agg`, `plt.show()` closes instead of
drawing). Unset, it follows the context: inline under a kernel, console
otherwise.

It is a **start-up** decision — matplotlib's backend cannot be swapped under a
running kernel — so `set_output_mode()` warns when a change cannot take effect
rather than pretending it did.

- `print_header(title)` — a formatted header when run as a script;
  jupytext-filter turns it into a markdown header in notebooks.
