"""Tests for hardware detection and the output axis."""

import builtins

import pytest

from jupytext_notebook_helper import machine as hw_module
from jupytext_notebook_helper import output as output_module
from jupytext_notebook_helper.machine import ENV_BACKEND, hardware
from jupytext_notebook_helper.output import (
    ENV_OUTPUT,
    OutputMode,
    current_output_mode,
    set_output_mode,
    skip_figures,
)


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in (ENV_BACKEND, ENV_OUTPUT, "SKIP_PLOTS"):
        monkeypatch.delenv(name, raising=False)
    hw_module._reset_for_tests()
    output_module._reset_for_tests()
    yield
    hw_module._reset_for_tests()
    output_module._reset_for_tests()


# ---------------------------------------------------------------------------
# Output mode
# ---------------------------------------------------------------------------


def test_output_defaults_to_console_outside_a_notebook():
    assert current_output_mode() is OutputMode.CONSOLE


@pytest.mark.parametrize(
    "written,expected",
    [
        ("off", OutputMode.OFF),
        ("OFF", OutputMode.OFF),
        ("notebook", OutputMode.NOTEBOOK),
        ("console", OutputMode.CONSOLE),
    ],
)
def test_output_reads_the_environment(monkeypatch, written, expected):
    monkeypatch.setenv(ENV_OUTPUT, written)
    assert current_output_mode() is expected


def test_an_unparseable_output_mode_warns_and_is_ignored(monkeypatch, caplog):
    monkeypatch.setenv(ENV_OUTPUT, "sideways")
    assert current_output_mode() is OutputMode.CONSOLE
    assert "sideways" in caplog.text


def test_skip_plots_still_forces_output_off(monkeypatch):
    """The legacy spelling keeps working for courses that have not migrated."""
    monkeypatch.setenv("SKIP_PLOTS", "1")
    assert current_output_mode() is OutputMode.OFF
    assert skip_figures()


def test_notebook_output_wins_over_skip_plots(monkeypatch):
    monkeypatch.setenv("SKIP_PLOTS", "1")
    monkeypatch.setenv(ENV_OUTPUT, "console")
    assert current_output_mode() is OutputMode.CONSOLE


def test_set_output_mode_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv(ENV_OUTPUT, "off")
    set_output_mode("console")
    assert current_output_mode() is OutputMode.CONSOLE


def test_set_output_mode_rejects_nonsense():
    with pytest.raises(ValueError, match="unknown output mode"):
        set_output_mode("sideways")


def test_changing_figure_output_after_set_up_warns():
    """matplotlib's backend is fixed at start-up; say so rather than lie."""
    output_module.mark_applied(OutputMode.OFF)
    with pytest.warns(RuntimeWarning, match="needs a restart"):
        set_output_mode(OutputMode.CONSOLE)


def test_switching_between_two_showing_modes_is_silent():
    output_module.mark_applied(OutputMode.CONSOLE)
    set_output_mode(OutputMode.NOTEBOOK)  # no warning: both draw figures


# ---------------------------------------------------------------------------
# Hardware
# ---------------------------------------------------------------------------


def test_hardware_without_torch_falls_back_to_cpu(monkeypatch):
    """The build half of this package must work on a machine with no torch."""
    real_import = builtins.__import__

    def no_torch(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("no torch here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_torch)
    hw = hardware(refresh=True)
    assert hw.backend == "cpu"
    assert hw.total_memory_gb == 0.0


@pytest.mark.parametrize("backend", ["cuda", "mps", "cpu"])
def test_the_backend_can_be_forced(monkeypatch, backend):
    monkeypatch.setenv(ENV_BACKEND, backend)
    assert hardware(refresh=True).backend == backend


def test_an_unknown_backend_warns_and_is_detected_instead(monkeypatch, caplog):
    monkeypatch.setenv(ENV_BACKEND, "tpu")
    hardware(refresh=True)
    assert "tpu" in caplog.text


def test_hardware_is_cached():
    assert hardware() is hardware()


def test_capability_flags_are_false_off_cuda(monkeypatch):
    monkeypatch.setenv(ENV_BACKEND, "mps")
    hw = hardware(refresh=True)
    assert not hw.has_bitsandbytes
    assert not hw.has_vllm
    assert not hw.has_flash_attention
    assert not hw.supports_bf16


def test_dtypes_follow_the_backend(monkeypatch):
    torch = pytest.importorskip("torch")
    monkeypatch.setenv(ENV_BACKEND, "cpu")
    hw = hardware(refresh=True)
    assert hw.dtype is torch.float32
    assert hw.train_dtype is torch.float32

    monkeypatch.setenv(ENV_BACKEND, "mps")
    hw = hardware(refresh=True)
    assert hw.dtype is torch.float16
    # LoRA in pure fp16 is unstable, so training stays in fp32 off CUDA.
    assert hw.train_dtype is torch.float32


def test_synchronize_and_empty_cache_are_safe_on_cpu(monkeypatch):
    pytest.importorskip("torch")
    monkeypatch.setenv(ENV_BACKEND, "cpu")
    hw = hardware(refresh=True)
    hw.synchronize()
    hw.empty_cache()
    assert hw.memory_used_gb() == 0.0


# ---------------------------------------------------------------------------
# Hardware meets a profile ladder
# ---------------------------------------------------------------------------


def _ladder():
    base = pytest.importorskip("cached_hub").Profile

    class Profile(base):
        FAST_TEST = 0
        SMALL = 1
        LOW_GPU = 2
        HIGH_GPU = 3

        @classmethod
        def detect(cls, hardware=None):
            if hardware is None or hardware.backend == "cpu":
                return cls.SMALL
            if hardware.backend == "cuda" and hardware.total_memory_gb >= 32:
                return cls.HIGH_GPU
            return cls.LOW_GPU

    Profile.reset()
    return Profile


def test_hardware_seeds_the_profile_from_the_machine(monkeypatch):
    Profile = _ladder()
    monkeypatch.setenv(ENV_BACKEND, "cpu")
    hw = hardware(Profile, refresh=True)
    assert hw.profile is Profile.SMALL


def test_mps_is_a_gpu(monkeypatch):
    """An Apple Silicon laptop is not a machine without a GPU."""
    Profile = _ladder()
    monkeypatch.setenv(ENV_BACKEND, "mps")
    hw = hardware(Profile, refresh=True)
    assert hw.profile is Profile.LOW_GPU


def test_the_environment_still_wins_over_detection(monkeypatch):
    Profile = _ladder()
    monkeypatch.setenv(ENV_BACKEND, "cpu")
    monkeypatch.setenv("NOTEBOOK_PROFILE", "fast-test")
    hw = hardware(Profile, refresh=True)
    assert hw.profile is Profile.FAST_TEST


def test_hardware_pick_delegates_to_the_ladder(monkeypatch):
    Profile = _ladder()
    monkeypatch.setenv(ENV_BACKEND, "cpu")
    hw = hardware(Profile, refresh=True)
    assert hw.pick(200, fast_test=8, small=40) == 40


def test_pick_without_a_ladder_says_so(monkeypatch):
    monkeypatch.setenv(ENV_BACKEND, "cpu")
    hw = hardware(refresh=True)
    with pytest.raises(RuntimeError, match="without a profile ladder"):
        hw.pick(200, small=40)
