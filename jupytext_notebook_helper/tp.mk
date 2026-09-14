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

.PHONY: all student notebooks teacher solution bundle check check-raw \
	check-bundle show-tests show-raw lab lab-test clean

# `help` used to be the first target here, and so the default goal; it now sits
# at the bottom, one section per kind of work, so say it explicitly — unless the
# project declared a target of its own before the include.
ifeq ($(.DEFAULT_GOAL),)
.DEFAULT_GOAL := help
endif

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
# ---- running the sources -------------------------------------------------
# How much work an automated run does, and where its output goes. `fast-test`
# is never auto-selected, so a check has to ask for it by name.
CHECK_PROFILE      ?= fast-test
CHECK_OUTPUT       ?= off
# Seconds before a runaway source is killed; empty means no limit. perl rather
# than timeout(1), which BSD/macOS does not ship.
CHECK_TIMEOUT      ?=
# Anything else to put in the environment, without editing a recipe:
#   make check NOTEBOOK_ENV="HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false"
NOTEBOOK_ENV       ?=

CHECK_ENV = NOTEBOOK_PROFILE=$(CHECK_PROFILE) NOTEBOOK_OUTPUT=$(CHECK_OUTPUT) \
            $(NOTEBOOK_ENV)
CHECK_LIMIT = $(if $(CHECK_TIMEOUT),perl -e 'alarm shift @ARGV; exec @ARGV or die' $(CHECK_TIMEOUT),)

# `make check:<name>` runs a single source.
check\:%:
	@$(MAKE) $(RESOLVED_DIR)/$*.resolved

$(RESOLVED_DIR)/%.resolved: $(SOURCES_DIR)/%.py | $(RESOLVED_DIR)
	@rm -f $(RESOLVED_DIR)/$*.failed $@
	@echo "== $* =="
	@$(CHECK_ENV) $(CHECK_LIMIT) $(RUN) $< \
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
	@$(CHECK_ENV) $(CHECK_LIMIT) $(PYTHON) python $< \
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
# $(LAB_DIR) defaults to $(TEACHER_DIR): only the teacher variant keeps the
# `from jupytext_notebook_helper import *` cell and the [[remove]] blocks.
#
# `lab-test` exports NOTEBOOK_PROFILE for the whole server, and the ladder reads
# it at import, so the rung is fixed per *kernel* — restart the kernel to change
# your mind, the server to change the value. Or leave it unset (`make lab`) and
# use the in-notebook chooser. A middle rung rather than `check`'s smallest:
# reduced work, but output still worth looking at.
#
# Note that editing a notebook in Lab does NOT write back to $(SOURCES_DIR):
# $(LAB_DIR) holds build outputs, overwritten as soon as the source is newer.
LAB_DIR       ?= $(TEACHER_DIR)
LAB           ?= $(PYTHON) jupyter lab
LAB_PROFILE   ?= small

lab: $(TEACHER_LOCAL)
	$(LAB) $(LAB_DIR)

lab-test: $(TEACHER_LOCAL)
	NOTEBOOK_PROFILE=$(LAB_PROFILE) $(NOTEBOOK_ENV) $(LAB) $(LAB_DIR)

# $(LEGACY_COLAB): pre-0.8 <name>.colab.ipynb outputs. $(TEACHER_DIR) and
# $(SOLUTION_DIR) go away wholesale, but $(DESTDIR_TP) is only cleaned file by
# file (it is often a shared static/ directory), so the old student Colab
# notebooks would otherwise survive the upgrade and keep being deployed.
clean:
	@rm -rf $(TEACHER_DIR) $(SOLUTION_DIR) $(DEPDIR) $(TESTED_DIR) $(RESOLVED_DIR) \
		$(BUNDLE_DIR) $(STUDENT_ENV_DIR) $(STUDENT_LOCAL) $(STUDENT_COLAB) \
		$(STUDENT_COLAB_DIR) $(LEGACY_COLAB) $(ZIP)

# ---- run-teacher: execute the teacher notebooks, and KEEP the result -------
#
# `check` runs the *sources* as scripts, to say pass or fail. This runs the
# built teacher notebooks through Jupyter, at whatever profile the environment
# asks for, and keeps the executed notebooks with their figures — made for a
# night on the best GPU around.
#
#   make run-teacher                        every notebook, profile auto-detected
#   make run-teacher:03-efficiency          just one
#   make run-teacher NOTEBOOK_PROFILE=small a smaller rung
#   make run-teacher RUN_TIMEOUT=1200       give up on a notebook after 20 min
#   make show-run                           the summary, once it is over
#   make check-teacher                      the same runner as a smoke test
#
# What is NOT run again. Each notebook has a stamp under $(RUN_DIR)/.done/,
# keyed by profile; the stamp depends on $(TEACHER_DIR)/<name>.ipynb, which
# itself depends on the source. So a notebook is re-run when its source
# changed, when the profile changed, or when the last run failed (a failure
# leaves no stamp) — and skipped otherwise. `make run-again` forgets every
# stamp. The executed notebook is kept either way: a failure is worth reading.
RUN_DIR     ?= run
#: Where figures go. These notebooks are meant to be read, not just to pass.
RUN_OUTPUT  ?= notebook
#: Wall-clock cap per notebook, in seconds. Empty means none.
RUN_TIMEOUT ?=
#: The rung a smoke test (`check-teacher`) drops to.
RUN_CHECK_PROFILE ?= fast-test

#: The rung actually in force, for the stamp path and the log line. Empty
#: NOTEBOOK_PROFILE is the interesting case: the ladder decides.
RUN_PROFILE_LABEL := $(if $(NOTEBOOK_PROFILE),$(NOTEBOOK_PROFILE),auto)
RUN_STAMP_DIR     := $(RUN_DIR)/.done
RUN_STAMPS        := $(NAMES:%=$(RUN_STAMP_DIR)/%.$(RUN_PROFILE_LABEL))

# NOTEBOOK_PROFILE is exported rather than set on the recipe line, so that
# `NOTEBOOK_PROFILE=small make run-teacher` and `make run-teacher
# NOTEBOOK_PROFILE=small` behave the same. Unset, it stays unset.
ifneq ($(NOTEBOOK_PROFILE),)
export NOTEBOOK_PROFILE
endif
RUN_ENV   = NOTEBOOK_OUTPUT=$(RUN_OUTPUT) $(NOTEBOOK_ENV)
RUN_LIMIT = $(if $(RUN_TIMEOUT),perl -e 'alarm shift @ARGV; exec @ARGV or die' $(RUN_TIMEOUT),)

.PHONY: run-teacher show-run run-again check-teacher
run-teacher\:%:
	@$(MAKE) $(RUN_STAMP_DIR)/$*.$(RUN_PROFILE_LABEL)

# A copy executed in place, rather than nbconvert into another directory: the
# kernel then starts in $(CURDIR), where $(SRC_ROOT)/ and the outputs are.
#
# --allow-errors so one broken cell does not throw away a night's work; the
# error is found afterwards in the saved notebook, and in the missing stamp.
# --timeout=-1 for the same reason: a legitimately slow cell is not a hung one,
# and RUN_TIMEOUT is what bounds a notebook as a whole.
$(RUN_STAMP_DIR)/%.$(RUN_PROFILE_LABEL): $(TEACHER_DIR)/%.ipynb
	@mkdir -p $(RUN_STAMP_DIR)
	@rm -f $(RUN_DIR)/$*.time
	@cp $< $(RUN_DIR)/$*.ipynb
	@echo "== $* (profile $(RUN_PROFILE_LABEL)) =="
	@start=$$(date +%s); \
	if $(RUN_ENV) $(RUN_LIMIT) $(PYTHON) jupyter execute --inplace \
			--allow-errors --timeout=-1 $(RUN_DIR)/$*.ipynb \
			> $(RUN_DIR)/$*.log 2>&1 \
		&& ! grep -q '"output_type": "error"' $(RUN_DIR)/$*.ipynb; then \
		ok=1; \
	else \
		ok=0; \
	fi; \
	elapsed=$$(( $$(date +%s) - start )); \
	echo "$$elapsed" > $(RUN_DIR)/$*.time; \
	if [ $$ok = 1 ]; then \
		touch $@; \
		printf "\033[32m  OK   %-28s %d min %02d s\033[0m\n" \
			"$*" "$$(( elapsed / 60 ))" "$$(( elapsed % 60 ))"; \
	else \
		printf "\033[31m  FAIL %-28s %d min %02d s — $(RUN_DIR)/$*.log\033[0m\n" \
			"$*" "$$(( elapsed / 60 ))" "$$(( elapsed % 60 ))"; \
	fi

run-teacher: | $(RUN_DIR)
	@$(MAKE) $(RUN_STAMPS)
	@echo "Done — 'make show-run' for the summary, $(RUN_DIR)/ for the notebooks"

$(RUN_DIR): ; @mkdir -p $@

# Forget the stamps, keep the notebooks: the next run starts over.
run-again:
	@rm -rf $(RUN_STAMP_DIR)
	@echo "Stamps cleared — the next 'make run-teacher' re-runs everything"

# The smoke test is the same runner at the smallest rung, with no figures.
check-teacher:
	@$(MAKE) run-teacher NOTEBOOK_PROFILE=$(RUN_CHECK_PROFILE) RUN_OUTPUT=off
check-teacher\:%:
	@$(MAKE) run-teacher:$* NOTEBOOK_PROFILE=$(RUN_CHECK_PROFILE) RUN_OUTPUT=off

show-run:
	@printf "  %-28s %-6s %-12s %s\n" "notebook" "state" "duration" "output"
	@printf "  %-28s %-6s %-12s %s\n" "--------" "-----" "--------" "------"
	@total=0; \
	for n in $(NAMES); do \
		if [ -f "$(RUN_STAMP_DIR)/$$n.$(RUN_PROFILE_LABEL)" ]; then s="[OK]"; \
		elif [ -f "$(RUN_DIR)/$$n.ipynb" ]; then s="[FAIL]"; \
		else s="[ -- ]"; fi; \
		if [ -f "$(RUN_DIR)/$$n.time" ]; then \
			t=$$(cat "$(RUN_DIR)/$$n.time"); \
			total=$$(( total + t )); \
			d=$$(printf "%d min %02d s" "$$(( t / 60 ))" "$$(( t % 60 ))"); \
		else d="-"; fi; \
		printf "  %-28s %-6s %-12s %s\n" "$$n" "$$s" "$$d" "$(RUN_DIR)/$$n.ipynb"; \
	done; \
	printf "  %-28s %-6s %d min %02d s  (profile $(RUN_PROFILE_LABEL))\n" \
		"total" "" "$$(( total / 60 ))" "$$(( total % 60 ))"

# ---- check-resources: the declared Hub resources vs. what the sources load --
# Only defined when the course points RESOURCES_PY at a cached-hub declaration
# module (e.g. src/mycourse/resources.py); `check` then depends on it.
#
# `cached-hub check` reads the load_hf_* calls back out of $(SOURCES_DIR) and
# fails when the declaration no longer describes them: a model added to a
# notebook, one that stopped being loaded. It works on the AST, without
# importing, so a resource built at run time is never executed by it — hence
# the second step, which imports the module for real and builds every resource
# object: that is what catches an import error, a typo in a factory argument,
# or a section that no longer loads.
#
# For a new notebook, a skeleton to fill in:
#     cached-hub scan $(SOURCES_DIR) --emit <section>
RESOURCES_PY ?=
#: Dotted module path of $(RESOURCES_PY), derived from $(SRC_ROOT).
RESOURCES_MODULE ?= $(subst /,.,$(patsubst $(SRC_ROOT)/%,%,$(basename $(RESOURCES_PY))))
CACHED_HUB ?= $(PYTHON) cached-hub

ifneq ($(strip $(RESOURCES_PY)),)
.PHONY: check-resources
check-resources:
	@$(CACHED_HUB) check $(SOURCES_DIR) --search-path $(SRC_ROOT) \
		--declaration $(RESOURCES_PY)
	@$(PYTHON) python -m $(RESOURCES_MODULE) list >/dev/null
	@echo "$(RESOURCES_MODULE) imports and lists its resources"
check: check-resources
endif

# ---- deployment -----------------------------------------------------------
# Only defined when the course sets SSH_HOST. $(DESTDIR_TP) is copied to
# $(SSH_HOST):$(SSH_PATH); RSYNC_DATA, if set, is symlinked into it as `data`
# first (a directory shared with the rest of the course site).
SSH_HOST ?=
SSH_PATH ?=
#: What of $(DESTDIR_TP) reaches the server. rsync never descends into a
#: directory it was not told to include, so "colab/" must come before
#: "*.ipynb" — without it the Colab notebooks silently stop being deployed.
RSYNC_INCLUDE ?= colab/ *.ipynb *.zip
#: Relative to $(DESTDIR_TP): symlinked there as `data` and deployed with the
#: notebooks. Empty means the course ships no data directory.
RSYNC_DATA ?=
#: Bulk data (caches, corpora) deployed separately, by `rsync-data`.
STUDENT_DATA_DIR ?= student-data
SSH_STUDENT_DATA ?=
SSH_STUDENT_DATA_PATH ?=

RSYNC_DATA_LINK := $(if $(RSYNC_DATA),$(DESTDIR_TP)/data)
RSYNC_ARGS := $(foreach i,$(RSYNC_INCLUDE) $(if $(RSYNC_DATA),data/ data/*),--include "$(i)")

ifneq ($(strip $(SSH_HOST)),)
.PHONY: rsync
$(RSYNC_DATA_LINK):
	ln -sf $(RSYNC_DATA) $@

rsync: student $(RSYNC_DATA_LINK)
	@echo "=== Synchronizing student notebooks on $(SSH_HOST) ==="
	@ssh $(SSH_HOST) mkdir -p $(SSH_PATH)
	rsync --copy-unsafe-links -azv $(RSYNC_ARGS) --exclude "*" --delete-excluded \
		$(DESTDIR_TP)/ $(SSH_HOST):$(SSH_PATH)
endif

ifneq ($(strip $(SSH_STUDENT_DATA)),)
.PHONY: rsync-data
rsync-data:
	rsync -azv --progress --partial --delete-excluded \
		$(STUDENT_DATA_DIR)/ $(SSH_STUDENT_DATA):$(SSH_STUDENT_DATA_PATH)
endif

# ---- practicals manifest --------------------------------------------------
# A JSON description of the practicals — id, display name, the files each one
# produces and the URL they are served from — for whatever announces them: a
# slide deck's index page, a course site. See manifest.py for the schema.
#
# It reads the sources' headers and builds nothing, so the consumer can refresh
# it before every one of its own builds. Nothing happens unless MANIFEST names
# a file to write:
#
#     make manifest MANIFEST=../slides/practicals.json \
#                   MANIFEST_RELATIVE_TO=host:/srv/course/slides
#
MANIFEST              ?=
# Where the notebooks are served from, as the manifest's reader sees them.
# Either said outright, or worked out from the two deployment paths: $(SSH_PATH)
# is where `make rsync` puts the notebooks, MANIFEST_RELATIVE_TO where the
# reader puts itself.
MANIFEST_BASE_URL     ?=
MANIFEST_RELATIVE_TO  ?=
# Labels the reader shows for the two variants of each notebook.
MANIFEST_LOCAL_LABEL  ?= Notebook
MANIFEST_COLAB_LABEL  ?= Colab
# Header key (under jupyter.metadata) holding a practical's display name.
MANIFEST_NAME_KEY     ?= practical_name

.PHONY: manifest
manifest:
	@test -n "$(MANIFEST)" || { \
		echo "ERROR: MANIFEST is not set — name the file to write, e.g."; \
		echo "       make manifest MANIFEST=../slides/practicals.json"; \
		exit 1; }
	@$(PYTHON) python -m jupytext_notebook_helper.manifest \
		--sources $(SOURCES_DIR) --colab-subdir "$(COLAB_SUBDIR)" \
		--output $(MANIFEST) --name-key "$(MANIFEST_NAME_KEY)" \
		--local-label "$(MANIFEST_LOCAL_LABEL)" \
		--colab-label "$(MANIFEST_COLAB_LABEL)" \
		$(if $(MANIFEST_BASE_URL),--base-url "$(MANIFEST_BASE_URL)") \
		$(if $(MANIFEST_RELATIVE_TO),--deploy-path "$(if $(strip $(SSH_HOST)),$(strip $(SSH_HOST)):)$(SSH_PATH)" \
			--relative-to "$(MANIFEST_RELATIVE_TO)")

# ---- outline ----------------------------------------------------------
# Per-notebook table of contents (headers + print_header() calls) with each
# [[student]]/[[assert]] marker nested under the section it appears in — a
# quick read of what a notebook covers and what it still leaves for the
# student. Reads the sources only, builds nothing.
# `make outline OUTLINE_NAMES=<name>` (or several, space-separated) restricts
# it to those notebooks; not called NAMES, which already lists every source.
OUTLINE_NAMES ?=

.PHONY: outline
outline:
	@$(PYTHON) python -m jupytext_notebook_helper.outline \
		--sources $(SOURCES_DIR) $(OUTLINE_NAMES)

# ---- help -----------------------------------------------------------------
# One section per kind of work. A course adds its own section by defining and
# EXPORTING HELP_PROJECT (printed last):
#
#     define HELP_PROJECT
#     Corpus
#       lotte-corpus     build the LoTTE tarball
#     endef
#     export HELP_PROJECT
HELP_PROJECT ?=

# The optional entries. They live in their own variables because a `$(if ...)`
# argument is split on the FIRST comma: written inline, a line of prose would be
# cut at its first comma, whereas a `$(VAR)` reference is one token and is
# expanded only afterwards.
define HELP_RESOURCES
  check-resources  check $(RESOURCES_PY) against the load_hf_* calls in
                   $(SOURCES_DIR)/ (cached-hub check), then import it for real
                   and build every resource. Run by 'check'. A skeleton for a
                   new notebook: cached-hub scan $(SOURCES_DIR) --emit <section>
endef

define HELP_RSYNC
  rsync            deploy $(DESTDIR_TP)/ to $(SSH_HOST):$(SSH_PATH)
endef

define HELP_RSYNC_DATA
  rsync-data       deploy $(STUDENT_DATA_DIR)/ to $(SSH_STUDENT_DATA)
endef

define HELP_TEXT

Build
  student          student notebooks (local + Colab) + uv zip
  teacher          teacher notebooks (local + Colab, with solutions)
  solution         student-facing solution / corrigé (local + Colab, with
                   solutions, no instructor cells/markers/tag comments)
  bundle           the uv-ready student zip only$(if $(BUNDLE_WITH_NOTEBOOKS),, (env only, no notebooks))
  all              student + teacher
  manifest         JSON description of the practicals (ids, names, files, URL)
                   for whatever announces them — reads the headers only, builds
                   no notebook. Needs MANIFEST=<file>; MANIFEST_BASE_URL or
                   MANIFEST_RELATIVE_TO says where they are served from.
  outline          per-notebook table of contents (headers + print_header())
                   with each [[student]]/[[assert]] marker nested under its
                   section — reads the sources only, builds no notebook.
                     OUTLINE_NAMES=<name> [<name> ...]  restrict to these
  clean            remove generated notebooks, $(TEACHER_DIR)/, zip, $(DEPDIR), $(TESTED_DIR)

Check the sources (run them as scripts, pass/fail)
  check            run every source with internal imports RESOLVED (the exact
                   inlined code students get) at profile $(CHECK_PROFILE), output
                   $(CHECK_OUTPUT); pass/fail under $(RESOLVED_DIR)/. The gate that
                   matches the built notebooks.
                     CHECK_PROFILE / CHECK_OUTPUT / CHECK_TIMEOUT to adjust
  check:<name>     a single source (e.g. make check:$(firstword $(NAMES)))
  check-raw        every source as a plain script (imports the full $(SRC_ROOT)/):
                   faster and looser, for early debugging; misses inlining bugs
  check-raw:<name> raw run of a single source
  show-tests       last 'check' pass/fail per source
  show-raw         last 'check-raw' pass/fail per source
  check-bundle     verify the zip resolves with uv (no install)$(if $(RESOURCES_PY),
$(HELP_RESOURCES))

Run the teacher notebooks (execute them, keep the result)
  run-teacher      every teacher notebook through Jupyter, at profile
                   '$(RUN_PROFILE_LABEL)'; executed notebooks and logs in $(RUN_DIR)/.
                   A notebook is re-run when its source changed, when the
                   profile changed, or when the last run failed — otherwise
                   it is skipped.
                     NOTEBOOK_PROFILE  fast-test|small|low-gpu|high-gpu;
                                       unset (the default) auto-detects
                     RUN_TIMEOUT       seconds before a notebook is given up
                     RUN_OUTPUT        notebook|console|off (now: $(RUN_OUTPUT))
  run-teacher:<name>  same, for one notebook
  check-teacher    the same runner as a smoke test: NOTEBOOK_PROFILE=$(RUN_CHECK_PROFILE)
                   and no figures. 'check-teacher:<name>' for one.
  run-again        forget the stamps, keep the notebooks
  show-run         state, duration and path, per notebook

Edit
  lab              JupyterLab on the teacher notebooks (built first)
  lab-test         same, at profile $(LAB_PROFILE): reduced datasets and training,
                   figures still shown$(if $(or $(SSH_HOST),$(SSH_STUDENT_DATA)),

Deploy)$(if $(SSH_HOST),
$(HELP_RSYNC))$(if $(SSH_STUDENT_DATA),
$(HELP_RSYNC_DATA))
endef
export HELP_TEXT

define HELP_FOOTER

Layout: <name>.ipynb next to the sources' output dir, Colab variants under
        $(COLAB_SUBDIR)/ — $(DESTDIR_TP)/$(COLAB_SUBDIR)/<name>.ipynb,
        $(TEACHER_DIR)/$(COLAB_SUBDIR)/<name>.ipynb, $(SOLUTION_DIR)/$(COLAB_SUBDIR)/<name>.ipynb

Sources: $(NAMES)
endef
export HELP_FOOTER

.PHONY: help
help:
	@echo "Practicals (jupytext-notebook-helper) — make targets"
	@printf '%s\n' "$$HELP_TEXT"
	@[ -z "$$HELP_PROJECT" ] || printf '\n%s\n' "$$HELP_PROJECT"
	@printf '%s\n' "$$HELP_FOOTER"

# ---- bookkeeping ----
# Auto-dependency files (listing the internal src/ modules inlined into each
# notebook) are written as a side effect of the filter (--depdir) and only
# *included* to add extra prerequisites — they are NOT prerequisites themselves
# (otherwise rewriting them on each build would make the build non-idempotent).
$(DEPDIR): ; @mkdir -p $@
$(TESTED_DIR): ; @mkdir -p $@
$(RESOLVED_DIR): ; @mkdir -p $@
-include $(wildcard $(DEPFILES))
