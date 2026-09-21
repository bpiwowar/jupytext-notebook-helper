"""Per-course settings, read from ``[tool.jupytext-notebook-helper]``.

The build knobs that describe a *course* rather than a *layout* — which
packages the install cell must carry or leave out, what the student
environment needs beyond the notebooks' own imports — belong with the course's
other metadata, not in its Makefile::

    # pyproject.toml
    [tool.jupytext-notebook-helper]
    pip-exclude = ["mycourse-internal"]
    pip-force-include = ["torchvision", "sentencepiece"]
    pip-relax = ["numpy", "torch"]
    student-base-deps = ["cs-lab>=1.0"]
    student-requires-python = ">=3.10, <3.12"
    student-env-name = "tp-student-env"

Every key is optional, and the corresponding make variable / command-line
option still wins, so a Makefile that sets nothing behaves exactly as before.
``pip-exclude``, ``pip-force-include``, ``pip-relax`` and
``student-base-deps`` *add* to what the command line passes rather than
replacing it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

#: Table read from the course's ``pyproject.toml``.
TOOL_TABLE = "jupytext-notebook-helper"

#: Packages the student environment gets whatever the notebooks import.
DEFAULT_STUDENT_BASE_DEPS = ("jupyter", "jupyterlab", "ipywidgets")

DEFAULT_STUDENT_ENV_NAME = "tp-student-env"
DEFAULT_STUDENT_REQUIRES_PYTHON = ">=3.10, <3.12"


@dataclass
class CourseConfig:
    """What ``[tool.jupytext-notebook-helper]`` says, with defaults filled in."""

    pip_exclude: List[str] = field(default_factory=list)
    pip_force_include: List[str] = field(default_factory=list)
    pip_relax: List[str] = field(default_factory=list)
    student_base_deps: List[str] = field(default_factory=list)
    student_env_name: str = DEFAULT_STUDENT_ENV_NAME
    student_requires_python: str = DEFAULT_STUDENT_REQUIRES_PYTHON
    source: Optional[Path] = None


#: Config key -> (attribute, expected type)
_KEYS = {
    "pip-exclude": ("pip_exclude", list),
    "pip-force-include": ("pip_force_include", list),
    "pip-relax": ("pip_relax", list),
    "student-base-deps": ("student_base_deps", list),
    "student-env-name": ("student_env_name", str),
    "student-requires-python": ("student_requires_python", str),
}


def load(root: Path | str = ".") -> CourseConfig:
    """Read the tool table from ``<root>/pyproject.toml`` (missing file is fine)."""
    path = Path(root) / "pyproject.toml"
    if not path.is_file():
        return CourseConfig()

    with open(path, "rb") as handle:
        table = tomllib.load(handle).get("tool", {}).get(TOOL_TABLE, {})
    if not table:
        return CourseConfig()

    config = CourseConfig(source=path)
    for key, value in table.items():
        entry = _KEYS.get(key)
        if entry is None:
            logging.warning("%s: unknown [tool.%s] key %r", path, TOOL_TABLE, key)
            continue
        attribute, expected = entry
        if not isinstance(value, expected):
            logging.warning(
                "%s: [tool.%s] %s should be a %s, ignoring",
                path,
                TOOL_TABLE,
                key,
                expected.__name__,
            )
            continue
        if expected is list:
            value = [str(item) for item in value]
        setattr(config, attribute, value)
    logging.debug("Course config from %s: %s", path, config)
    return config
