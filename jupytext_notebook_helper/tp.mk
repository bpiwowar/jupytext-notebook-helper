# Reusable make rules for jupytext-percent teaching practicals.
#
# Include from a project Makefile (after setting any project-specific variables):
#
#     ZIP      := ../static/tp/tp-mycourse-uv.zip
#     include $(shell uv run python -m jupytext_notebook_helper.tpmk)
#
# Course-level package lists belong in the course's pyproject.toml rather than
# here (see jupytext_notebook_helper/config.py):
#
#     [tool.jupytext-notebook-helper]
#     pip-force-include = ["sentencepiece"]   # not imported, still needed
#     pip-exclude = ["mycourse-internal"]     # never pip-installed by students
#     student-base-deps = ["cached-hub>=0.3.0"]
#
# Generates four variants per source plus a uv bundle. The Colab variants live
# in a `$(COLAB_SUBDIR)/` sub-directory of each output directory (they used to be
# named `<name>.colab.ipynb` next to the local ones — see `clean` below):
#   $(SOURCES_DIR)/<name>.py -> $(DESTDIR_TP)/<name>.ipynb          student . local
#                            -> $(DESTDIR_TP)/colab/<name>.ipynb    student . Colab (self-installs)
#                            -> $(TEACHER_DIR)/<name>.ipynb         teacher . local (solutions)
#                            -> $(TEACHER_DIR)/colab/<name>.ipynb   teacher . Colab
#                            +  $(ZIP) = pyproject + uv.lock + local notebooks + README
#                                       (BUNDLE_NOTEBOOKS=no drops the notebooks,
#                                        BUNDLE_EXTRA adds files at the zip root)
#   The zip only ever carries the *local* notebooks: it ships a pinned uv env, so
#   the self-installing Colab variants would be redundant there.
#
# Optional `make solution` adds a student-facing corrigé (solutions kept, but no
# instructor cells / [[...]] markers / tag comments):
#   $(SOURCES_DIR)/<name>.py -> $(SOLUTION_DIR)/<name>.ipynb        solution . local
#                            -> $(SOLUTION_DIR)/colab/<name>.ipynb  solution . Colab
#
# Cell-tag gating (in the sources): [[student]]..[[/student]] blanks solutions;
# tags `teacher`, `colab`, `not-colab`. The Colab `%pip install` cell is inserted
# automatically (before the first code cell) for the .colab variants; an empty
# `pip`-tagged cell is only needed to place it somewhere else.

# ---- configurable variables (override before the include) ----
SOURCES_DIR    ?= sources
DESTDIR_TP     ?= ../static/tp
TEACHER_DIR    ?= teacher
SOLUTION_DIR   ?= solution
# Sub-directory (of each of the three output directories above) holding the
# Colab variants, e.g. student/colab/<name>.ipynb. Must not be empty.
COLAB_SUBDIR   ?= colab
ROOT           ?= ..
PYTHON         ?= uv run
# Directory holding the internal library modules that get inlined when a source
# does `from <module> import <names>` (see the filter's --src-root).
SRC_ROOT       ?= src
DEPDIR         ?= .deps
TESTED_DIR     ?= .tested
RESOLVED_DIR   ?= .resolved
BUNDLE_DIR     ?= .tp-bundle
ZIP            ?= $(DESTDIR_TP)/tp-uv.zip
STUDENT_README ?= $(SOURCES_DIR)/STUDENT_README.md
# The student bundle ships a minimal env GENERATED from the union of the
# per-notebook `.pkgs` manifests (written by the filter when building the Colab/pip
# variant) plus a small base — never the repo's pyproject (which carries editable /
# instructor deps that break `uv sync` once unzipped elsewhere).
STUDENT_ENV_DIR       ?= student-env
STUDENT_ENV_NAME      ?= tp-student-env
STUDENT_REQUIRES_PYTHON ?= >=3.10, <3.12
# Added to what the notebooks import. jupyter / jupyterlab / ipywidgets are
# always included; a course's own additions are better placed in its
# pyproject.toml ([tool.jupytext-notebook-helper] student-base-deps), which can
# carry version constraints without shell quoting.
STUDENT_BASE_DEPS     ?=
BUNDLE_PYPROJECT      ?= $(STUDENT_ENV_DIR)/pyproject.toml
BUNDLE_LOCK           ?= $(STUDENT_ENV_DIR)/uv.lock
# Ship the student notebooks inside the bundle (default). Set to `no` for an
# environment-only archive — uv project + README (+ $(BUNDLE_EXTRA)) — that
# students can download once to pre-build the env / pre-download models while
# the notebooks are still being written and distributed separately.
BUNDLE_NOTEBOOKS      ?= yes
# Extra files copied at the ROOT of the bundle, e.g. a standalone pre-download
# script: BUNDLE_EXTRA := src/mylib/resources.py
BUNDLE_EXTRA          ?=
# Passed to the filter for the Colab install cell; --uv-root tells it where
# uv.lock/pyproject.toml live (relative to the build dir).
PIP_ARGS       ?= --uv-root $(ROOT)

# `yes` unless BUNDLE_NOTEBOOKS says otherwise (no/false/0/off, any case).
ifeq ($(filter $(BUNDLE_NOTEBOOKS),no No NO false False FALSE 0 off Off OFF),)
BUNDLE_WITH_NOTEBOOKS := yes
else
BUNDLE_WITH_NOTEBOOKS :=
endif

FILTER := $(PYTHON) python -m jupytext_notebook_helper.filter --src-root $(SRC_ROOT)
RUN    := $(PYTHON) python -m jupytext_notebook_helper.run --src-root $(SRC_ROOT)

ifeq ($(strip $(COLAB_SUBDIR)),)
$(error COLAB_SUBDIR must not be empty: the Colab notebooks need their own sub-directory)
endif

STUDENT_COLAB_DIR  := $(DESTDIR_TP)/$(COLAB_SUBDIR)
TEACHER_COLAB_DIR  := $(TEACHER_DIR)/$(COLAB_SUBDIR)
SOLUTION_COLAB_DIR := $(SOLUTION_DIR)/$(COLAB_SUBDIR)

PY_NOTEBOOKS  := $(wildcard $(SOURCES_DIR)/*.py)
NAMES         := $(patsubst $(SOURCES_DIR)/%.py,%,$(PY_NOTEBOOKS))
STUDENT_LOCAL := $(NAMES:%=$(DESTDIR_TP)/%.ipynb)
STUDENT_COLAB := $(NAMES:%=$(STUDENT_COLAB_DIR)/%.ipynb)
TEACHER_LOCAL := $(NAMES:%=$(TEACHER_DIR)/%.ipynb)
TEACHER_COLAB := $(NAMES:%=$(TEACHER_COLAB_DIR)/%.ipynb)
SOLUTION_LOCAL := $(NAMES:%=$(SOLUTION_DIR)/%.ipynb)
SOLUTION_COLAB := $(NAMES:%=$(SOLUTION_COLAB_DIR)/%.ipynb)
# Pre-0.8 output names, removed by `clean` so an upgraded checkout does not keep
# serving stale <name>.colab.ipynb next to the new colab/<name>.ipynb.
LEGACY_COLAB  := $(NAMES:%=$(DESTDIR_TP)/%.colab.ipynb) \
                 $(NAMES:%=$(TEACHER_DIR)/%.colab.ipynb) \
                 $(NAMES:%=$(SOLUTION_DIR)/%.colab.ipynb)
DEPFILES      := $(NAMES:%=$(DEPDIR)/%.d)
TESTED        := $(NAMES:%=$(TESTED_DIR)/%.tested)
RESOLVED      := $(NAMES:%=$(RESOLVED_DIR)/%.resolved)

.PHONY: help all student notebooks teacher solution bundle check check-raw \
	check-bundle show-tests show-raw lab lab-test clean
help:
	@echo "Practicals targets:"
	@echo "  student          student notebooks (local + Colab) + uv zip"
	@echo "  teacher          teacher notebooks (local + Colab, with solutions)"
	@echo "  solution         student-facing solution / corrigé (local + Colab, with"
	@echo "                   solutions, no instructor cells/markers/tag comments)"
	@echo "  bundle           the uv-ready student zip only$(if $(BUNDLE_WITH_NOTEBOOKS),, (env only, no notebooks))"
	@echo "  check-bundle     verify the zip resolves with uv (no install)"
	@echo "  all              student + teacher"
	@echo "  check            run every source with internal imports RESOLVED (the"
	@echo "                   exact inlined code students get); TESTING_MODE, figures"
	@echo "                   via imgcat, pass/fail under $(RESOLVED_DIR)/. This is the"
	@echo "                   gate that matches the built notebooks."
	@echo "  check:<name>     run a single source (e.g. make check:tp1-embeddings)"
	@echo "  check-raw        run every source as a plain script (imports full src/):"
	@echo "                   faster/looser, for early debugging; misses inlining bugs"
	@echo "  check-raw:<name> raw run of a single source"
	@echo "  show-tests       show last 'check' pass/fail status per source"
	@echo "  show-raw         show last 'check-raw' pass/fail status per source"
	@echo "  lab              JupyterLab on the teacher notebooks (built first)"
	@echo "  lab-test         same, with TESTING_MODE=$(LAB_TEST_MODE): reduced"
	@echo "                   datasets/training, plots still shown"
	@echo "  clean            remove generated notebooks, teacher/, zip, $(DEPDIR), $(TESTED_DIR)"
	@echo "                   (also the pre-0.8 <name>.colab.ipynb outputs)"
	@echo ""
	@echo "Layout: <name>.ipynb next to the sources' output dir, Colab variants"
	@echo "        under $(COLAB_SUBDIR)/ — $(DESTDIR_TP)/$(COLAB_SUBDIR)/<name>.ipynb,"
	@echo "        $(TEACHER_DIR)/$(COLAB_SUBDIR)/<name>.ipynb, $(SOLUTION_DIR)/$(COLAB_SUBDIR)/<name>.ipynb"
	@echo ""
	@echo "Sources: $(NAMES)"

all: student teacher
student: $(STUDENT_LOCAL) $(STUDENT_COLAB) $(ZIP)
notebooks: student  # backward-compatible alias
teacher: $(TEACHER_LOCAL) $(TEACHER_COLAB)
solution: $(SOLUTION_LOCAL) $(SOLUTION_COLAB)
bundle: $(ZIP)

# The Colab rules must be declared BEFORE the matching local ones: both patterns
# match e.g. student/colab/tp1.ipynb, and although make picks the shortest stem
# (`tp1` here, against `colab/tp1` for the local pattern) rather than the first
# rule, keeping them in this order makes the intent readable. The local rules
# stay safe either way: their prerequisite would be $(SOURCES_DIR)/colab/tp1.py,
# which does not exist, so they cannot apply to a file under $(COLAB_SUBDIR)/.
# Every recipe creates its own directory with `mkdir -p $(@D)`.

# student . Colab — auto `%pip install` cell, no solutions, drop not-colab.
$(STUDENT_COLAB_DIR)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(@D)
	$(FILTER) --depdir $(DEPDIR) --colab --exclude teacher,not-colab $(PIP_ARGS) $< > $@ || rm -f "$@"

# student . local — no install cell, no solutions.
$(DESTDIR_TP)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(@D)
	$(FILTER) --depdir $(DEPDIR) --exclude teacher,colab,pip $< > $@ || rm -f "$@"

# teacher . Colab — solutions + auto `%pip install` cell (no not-colab helper).
$(TEACHER_COLAB_DIR)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(@D)
	$(FILTER) --depdir $(DEPDIR) --colab --teacher --exclude not-colab $(PIP_ARGS) $< > $@ || rm -f "$@"

# teacher . local — solutions, instructor helper cell kept.
$(TEACHER_DIR)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(@D)
	$(FILTER) --depdir $(DEPDIR) --teacher --exclude colab,pip $< > $@ || rm -f "$@"

# solution (corrigé) . Colab — solutions kept, auto `%pip install` cell, but no
# instructor content: teacher-tagged cells dropped, no tag comments, no markers.
$(SOLUTION_COLAB_DIR)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(@D)
	$(FILTER) --depdir $(DEPDIR) --colab --solution --exclude teacher,not-colab $(PIP_ARGS) $< > $@ || rm -f "$@"

# solution (corrigé) . local — solutions kept, no install cell, no instructor content.
$(SOLUTION_DIR)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(@D)
	$(FILTER) --depdir $(DEPDIR) --solution --exclude teacher,colab,pip $< > $@ || rm -f "$@"

# Generated student env: union of the per-notebook package manifests (written by
# the filter into $(DEPDIR)/<name>.pkgs while building the Colab variant) + a small
# base to run notebooks. Depends on the Colab notebooks so the manifests exist.
$(STUDENT_ENV_DIR)/pyproject.toml: $(STUDENT_COLAB) $(ROOT)/pyproject.toml
	@$(PYTHON) python -m jupytext_notebook_helper.studentenv \
	  --depdir $(DEPDIR) --uv-root $(ROOT) --output $@ \
	  --name '$(STUDENT_ENV_NAME)' \
	  --requires-python '$(STUDENT_REQUIRES_PYTHON)' \
	  $(foreach dep,$(STUDENT_BASE_DEPS),--base-dep '$(dep)')

$(STUDENT_ENV_DIR)/uv.lock: $(STUDENT_ENV_DIR)/pyproject.toml
	cd $(STUDENT_ENV_DIR) && uv lock

# Self-contained uv bundle for local student use. The notebooks are only a
# prerequisite when they are actually shipped (BUNDLE_NOTEBOOKS): otherwise the
# archive is env-only and must stay stable while the notebooks are edited.
BUNDLE_NOTEBOOK_DEPS := $(if $(BUNDLE_WITH_NOTEBOOKS),$(STUDENT_LOCAL))

$(ZIP): $(BUNDLE_NOTEBOOK_DEPS) $(BUNDLE_PYPROJECT) $(BUNDLE_LOCK) $(STUDENT_README) $(BUNDLE_EXTRA)
	@rm -rf $(BUNDLE_DIR)
	@mkdir -p $(BUNDLE_DIR) $(dir $(ZIP))
	cp $(BUNDLE_PYPROJECT) $(BUNDLE_DIR)/pyproject.toml
	cp $(BUNDLE_LOCK) $(BUNDLE_DIR)/uv.lock
	cp $(STUDENT_README) $(BUNDLE_DIR)/README.md
# $(STUDENT_LOCAL) only: the bundle ships the pinned uv env, so the
# self-installing Colab notebooks have no place in it (unchanged behaviour).
ifdef BUNDLE_WITH_NOTEBOOKS
	@mkdir -p $(BUNDLE_DIR)/notebooks
	cp $(STUDENT_LOCAL) $(BUNDLE_DIR)/notebooks/
endif
	$(if $(BUNDLE_EXTRA),cp $(BUNDLE_EXTRA) $(BUNDLE_DIR)/)
	rm -f $(ZIP)
	cd $(BUNDLE_DIR) && zip -r -q $(abspath $(ZIP)) . && cd -
	@rm -rf $(BUNDLE_DIR)
	@echo "Built $(ZIP)$(if $(BUNDLE_WITH_NOTEBOOKS),, (no notebooks))"

# Resolution test for the bundle: unzip and verify `uv` can resolve the env from
# the shipped pyproject + uv.lock — WITHOUT installing anything (`uv lock --check`).
# Catches e.g. stray editable/path deps that only exist on the instructor's machine.
check-bundle: $(ZIP)
	@tmp=$$(mktemp -d); \
	unzip -q $(ZIP) -d $$tmp; \
	echo "Checking uv resolution of the bundle ..."; \
	if (cd $$tmp && uv lock --check) >/dev/null 2>$$tmp/err; then \
		echo "  PASS: bundle resolves (uv.lock consistent with pyproject)"; rm -rf $$tmp; \
	else \
		echo "  FAIL: bundle does not resolve:"; sed 's/^/    /' $$tmp/err; rm -rf $$tmp; exit 1; \
	fi

# ---- check: run each source with internal imports RESOLVED (the default) ----
# Executes exactly the inlined subset a student notebook will contain, so a
# tree-shaking bug (a symbol a copied helper needs, or a module-level side
# effect that was not inlined) surfaces here as a NameError / runtime error —
# at the real source location. This is what students actually get, so it is the
# default `check`. Use `check-raw` for the looser, faster script run.
# `make check:<name>` runs a single source.
check\:%:
	@$(MAKE) $(RESOLVED_DIR)/$*.resolved

$(RESOLVED_DIR)/%.resolved: $(SOURCES_DIR)/%.py | $(RESOLVED_DIR)
	@rm -f $(RESOLVED_DIR)/$*.failed $@
	@echo "== $* =="
	@TESTING_MODE=full $(RUN) $< \
		&& (touch $@ && printf '\033[32m  PASS %s\033[0m\n' "$*") \
		|| (touch $(RESOLVED_DIR)/$*.failed && printf '\033[31m  FAIL %s\033[0m\n' "$*")

check: $(RESOLVED)
	@echo "Done — see 'make show-tests'"

show-tests:
	@printf "  %-28s %s\n" "source" "status"
	@printf "  %-28s %s\n" "------" "------"
	@for n in $(NAMES); do \
		if [ -f "$(RESOLVED_DIR)/$$n.resolved" ]; then s="[PASS]"; \
		elif [ -f "$(RESOLVED_DIR)/$$n.failed" ]; then s="[FAIL]"; \
		else s="[ -- ]"; fi; \
		printf "  %-28s %s\n" "$$n" "$$s"; \
	done

# ---- check-raw: run each source as a plain script (imports the full src/ ----
# module). Faster and looser than `check`; handy for early debugging, but it
# CANNOT catch inlining / tree-shaking bugs (the whole module is importable).
# `make check-raw:<name>` runs a single source.
check-raw\:%:
	@$(MAKE) $(TESTED_DIR)/$*.tested

$(TESTED_DIR)/%.tested: $(SOURCES_DIR)/%.py | $(TESTED_DIR)
	@rm -f $(TESTED_DIR)/$*.failed $@
	@echo "== $* (raw) =="
	@TESTING_MODE=full $(PYTHON) python $< \
		&& (touch $@ && printf '\033[32m  PASS %s\033[0m\n' "$*") \
		|| (touch $(TESTED_DIR)/$*.failed && printf '\033[31m  FAIL %s\033[0m\n' "$*")

check-raw: $(TESTED)
	@echo "Done — see 'make show-raw'"

show-raw:
	@printf "  %-28s %s\n" "source" "status"
	@printf "  %-28s %s\n" "------" "------"
	@for n in $(NAMES); do \
		if [ -f "$(TESTED_DIR)/$$n.tested" ]; then s="[PASS]"; \
		elif [ -f "$(TESTED_DIR)/$$n.failed" ]; then s="[FAIL]"; \
		else s="[ -- ]"; fi; \
		printf "  %-28s %s\n" "$$n" "$$s"; \
	done

# ---- lab: JupyterLab on the built teacher notebooks ----
# Only the teacher variant keeps the `from jupytext_notebook_helper import *`
# cell, so `test_mode` (and the [[remove]] blocks that use it) exist there and
# nowhere else — hence $(LAB_DIR) defaults to $(TEACHER_DIR).
#
# `lab-test` exports TESTING_MODE for the whole server, and the helper reads it
# at import: the mode is therefore fixed per *kernel* (restart the kernel after
# changing your mind, restart the server to change the value). `on`, not `full`
# as in `check`: reduced datasets and training, but plots must stay visible when
# working interactively.
#
# Note that editing a notebook in Lab does NOT write back to $(SOURCES_DIR):
# $(LAB_DIR) holds build outputs, overwritten as soon as the source is newer.
LAB_DIR       ?= $(TEACHER_DIR)
LAB           ?= $(PYTHON) jupyter lab
LAB_TEST_MODE ?= on

lab: $(TEACHER_LOCAL)
	$(LAB) $(LAB_DIR)

lab-test: $(TEACHER_LOCAL)
	TESTING_MODE=$(LAB_TEST_MODE) $(LAB) $(LAB_DIR)

# $(LEGACY_COLAB): pre-0.8 <name>.colab.ipynb outputs. $(TEACHER_DIR) and
# $(SOLUTION_DIR) go away wholesale, but $(DESTDIR_TP) is only cleaned file by
# file (it is often a shared static/ directory), so the old student Colab
# notebooks would otherwise survive the upgrade and keep being deployed.
clean:
	@rm -rf $(TEACHER_DIR) $(SOLUTION_DIR) $(DEPDIR) $(TESTED_DIR) $(RESOLVED_DIR) \
		$(BUNDLE_DIR) $(STUDENT_ENV_DIR) $(STUDENT_LOCAL) $(STUDENT_COLAB) \
		$(STUDENT_COLAB_DIR) $(LEGACY_COLAB) $(ZIP)

# ---- bookkeeping ----
# Auto-dependency files (listing the internal src/ modules inlined into each
# notebook) are written as a side effect of the filter (--depdir) and only
# *included* to add extra prerequisites — they are NOT prerequisites themselves
# (otherwise rewriting them on each build would make the build non-idempotent).
$(DEPDIR): ; @mkdir -p $@
$(TESTED_DIR): ; @mkdir -p $@
$(RESOLVED_DIR): ; @mkdir -p $@
-include $(wildcard $(DEPFILES))
