"""The percent-format header of a jupytext source, read on its own.

A source's YAML header carries what the *course* knows about the practical and
the notebook build does not: its display name, its one-line description,
whether it is handed out at all. Reading it builds nothing and imports no
notebook, so every consumer here — the practicals manifest, the index page,
the selection of what is published — can afford to re-read every source on
every run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def read_header(source: Path) -> dict[str, Any]:
    """The percent-format YAML header of a jupytext source, as a dict.

    Only the header is read — the comment block between the first two ``# ---``
    lines — so the cost does not grow with the notebook.
    """
    lines: list[str] = []
    started = False
    with source.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.rstrip("\n")
            if stripped == "# ---":
                if started:
                    break
                started = True
                continue
            if not started:
                # Anything before the header means there is none.
                if stripped.strip():
                    return {}
                continue
            if not stripped.startswith("#"):
                return {}
            lines.append(stripped[2:] if stripped.startswith("# ") else stripped[1:])
    if not lines:
        return {}
    try:
        header = yaml.safe_load("\n".join(lines))
    except yaml.YAMLError:
        return {}
    return header if isinstance(header, dict) else {}


def metadata_value(source: Path, key: str) -> str | None:
    """A ``jupyter.metadata`` string of the header, stripped, or ``None``."""
    header = read_header(source)
    jupyter = header.get("jupyter") if isinstance(header, dict) else None
    if isinstance(jupyter, dict):
        metadata = jupyter.get("metadata")
        if isinstance(metadata, dict):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def display_name(source: Path, name_key: str) -> str:
    """The practical's title, from the header, or the file name title-cased."""
    value = metadata_value(source, name_key)
    if value is not None:
        return value
    return " ".join(word.capitalize() for word in source.stem.split("-"))
