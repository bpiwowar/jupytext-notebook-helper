"""Print the path to the bundled tp.mk make fragment.

Usage in a project Makefile:

    include $(shell uv run python -m jupytext_notebook_helper.tpmk)
"""

import pathlib

print(pathlib.Path(__file__).parent / "tp.mk")
