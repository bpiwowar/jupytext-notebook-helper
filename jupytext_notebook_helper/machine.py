"""What the machine actually offers: device, dtype, and which libraries work.

Separate from :class:`cached_hub.Profile`, which says how much compute to
*spend*. The two questions kept getting confused — a notebook would write
``device.type == "cuda"`` to mean "is this machine big" when it meant "does
``bitsandbytes`` exist here", and an Apple Silicon laptop with 128 GB of
unified memory would come out on the wrong side of both.

So: ask the profile how much work to do, and ask :func:`hardware` what to run
it on.

    hw = hardware(Profile)
    model = load_hf_model(MODEL_NAME, AutoModelForCausalLM, dtype=hw.dtype)
    model.to(hw.device)

    if hw.has_vllm:          # the library exists *and* the backend supports it
        ...

MPS is treated as what it is — a GPU — and capability flags are about library
availability rather than vendor: ``bitsandbytes`` and ``vllm`` are CUDA-only
because they cannot install elsewhere, not because MPS is second-class.

``torch`` is imported lazily, so this module (and the build tooling that shares
the package) stays importable without it.

Environment variables
---------------------
``NOTEBOOK_BACKEND``
    Force ``cuda``, ``mps`` or ``cpu`` instead of detecting. For reproducing a
    CPU-only run on a machine that has an accelerator.
"""

import logging
import os
from importlib.util import find_spec
from typing import Any, Optional

logger = logging.getLogger(__name__)

ENV_BACKEND = "NOTEBOOK_BACKEND"

BACKENDS = ("cuda", "mps", "cpu")

_hardware: Optional["Hardware"] = None


def _detect_backend() -> str:
    """CUDA, else MPS, else CPU — unless ``NOTEBOOK_BACKEND`` says otherwise."""
    forced = os.environ.get(ENV_BACKEND)
    if forced is not None and forced.strip():
        wanted = forced.strip().lower()
        if wanted in BACKENDS:
            return wanted
        logger.warning(
            "ignoring %s=%r; expected one of %s",
            ENV_BACKEND,
            forced,
            ", ".join(BACKENDS),
        )

    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None:
        if torch.backends.mps.is_available():
            return "mps"
    return "cpu"


def _memory_gb(backend: str) -> float:
    """Memory the accelerator can use, in GB (0.0 when there is no accelerator)."""
    try:
        import torch
    except ImportError:
        return 0.0
    # Deliberately broad: this is best-effort introspection, and a forced
    # backend the machine does not have raises anything from AttributeError to
    # a bare AssertionError ("Torch not compiled with CUDA enabled"). Not
    # knowing how much memory there is must never stop a notebook.
    try:
        if backend == "cuda":
            properties = torch.cuda.get_device_properties(0)
            return properties.total_memory / 1e9
        if backend == "mps":
            # Unified memory: what the driver is willing to hand to the GPU.
            return torch.mps.recommended_max_memory() / 1e9
    except Exception as error:  # noqa: BLE001
        logger.debug("could not read %s memory: %s", backend, error)
    return 0.0


def _device_name(backend: str) -> str:
    try:
        import torch
    except ImportError:
        return backend
    if backend == "cuda":
        try:
            return torch.cuda.get_device_name(0)
        except Exception:  # noqa: BLE001 - see _memory_gb
            return "cuda"
    return backend


class Hardware:
    """The machine, as a notebook needs to know it.

    ``backend``, ``device`` and the capability flags are facts, fixed once.
    ``profile``, ``dtype`` and ``train_dtype`` are read live, so switching
    profile from the widget and re-running a cell is honoured.
    """

    def __init__(self, backend: str, total_memory_gb: float, name: str, profiles=None):
        self.backend = backend
        self.total_memory_gb = total_memory_gb
        self.name = name
        self._profiles = profiles

    # -- what to run on ----------------------------------------------------

    @property
    def device(self):
        """The ``torch.device`` to put tensors on."""
        import torch

        return torch.device(self.backend)

    @property
    def supports_bf16(self) -> bool:
        """True when bfloat16 is usable, which in practice means CUDA.

        MPS advertises bfloat16 but is inconsistent about it, and CPU bf16 is
        slow enough not to be worth the surprise.
        """
        if self.backend != "cuda":
            return False
        try:
            import torch

            return bool(torch.cuda.is_bf16_supported())
        except Exception:  # noqa: BLE001 - see _memory_gb
            return False

    @property
    def dtype(self):
        """Dtype for inference: bf16 on CUDA, fp16 on MPS, fp32 on CPU."""
        import torch

        if self.backend == "cuda":
            return torch.bfloat16 if self.supports_bf16 else torch.float16
        if self.backend == "mps":
            return torch.float16
        return torch.float32

    @property
    def train_dtype(self):
        """Dtype for training: bf16 on CUDA, fp32 everywhere else.

        LoRA in pure fp16, without bf16's range, is unstable — so off CUDA the
        answer is fp32 even though inference is happy in fp16.
        """
        import torch

        if self.backend == "cuda" and self.supports_bf16:
            return torch.bfloat16
        return torch.float32

    # -- which libraries actually work here --------------------------------

    @property
    def has_bitsandbytes(self) -> bool:
        """4-bit quantization: needs a CUDA build."""
        return self.backend == "cuda" and find_spec("bitsandbytes") is not None

    @property
    def has_vllm(self) -> bool:
        """vLLM installs on Linux + CUDA only."""
        return self.backend == "cuda" and find_spec("vllm") is not None

    @property
    def has_flash_attention(self) -> bool:
        return self.backend == "cuda" and find_spec("flash_attn") is not None

    # -- how much work to do -----------------------------------------------

    @property
    def profile(self):
        """The active rung of the ladder handed to :func:`hardware`."""
        if self._profiles is None:
            return None
        return self._profiles.current()

    def pick(self, *default, **by_rung):
        """Shorthand for ``Profile.pick`` on the ladder given to :func:`hardware`."""
        if self._profiles is None:
            raise RuntimeError(
                "hardware() was called without a profile ladder; "
                "pass one, as in hardware(Profile)"
            )
        return self._profiles.pick(*default, **by_rung)

    # -- housekeeping the notebooks used to write by hand -------------------

    def synchronize(self) -> None:
        """Wait for the accelerator, so a timing measures what it claims to."""
        import torch

        if self.backend == "cuda":
            torch.cuda.synchronize()
        elif self.backend == "mps":
            torch.mps.synchronize()

    def empty_cache(self) -> None:
        """Hand cached blocks back, between two models that will not both fit."""
        import torch

        if self.backend == "cuda":
            torch.cuda.empty_cache()
        elif self.backend == "mps":
            torch.mps.empty_cache()

    def memory_used_gb(self) -> float:
        """Accelerator memory currently allocated, in GB."""
        try:
            import torch

            if self.backend == "cuda":
                return torch.cuda.memory_allocated() / 1e9
            if self.backend == "mps":
                return torch.mps.current_allocated_memory() / 1e9
        except Exception:  # noqa: BLE001 - see _memory_gb
            pass
        return 0.0

    def __str__(self) -> str:
        out = f"{self.name} ({self.backend}"
        if self.total_memory_gb:
            out += f", {self.total_memory_gb:.0f} GB"
        out += ")"
        if self.profile is not None:
            out += f" — profile {self.profile.name}"
        return out

    __repr__ = __str__


def hardware(profiles: Any = None, *, refresh: bool = False) -> Hardware:
    """Describe this machine, once, and let ``profiles`` size itself to it.

    ``profiles`` is a :class:`cached_hub.Profile` subclass. When given, its
    :meth:`detect` maps this machine to a rung, recorded as the default — so
    ``NOTEBOOK_PROFILE`` and the widget still win.
    """
    global _hardware
    if _hardware is None or refresh:
        backend = _detect_backend()
        _hardware = Hardware(
            backend=backend,
            total_memory_gb=_memory_gb(backend),
            name=_device_name(backend),
            profiles=profiles,
        )
    elif profiles is not None:
        _hardware._profiles = profiles

    if profiles is not None:
        profiles.set_detected(profiles.detect(_hardware))
    return _hardware


def _reset_for_tests() -> None:
    global _hardware
    _hardware = None
