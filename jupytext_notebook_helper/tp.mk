# Reusable make rules for jupytext-percent teaching practicals.
#
# Include from a project Makefile (after setting any project-specific variables):
#
#     ZIP      := ../static/tp/tp-mycourse-uv.zip
#     PIP_ARGS := --uv-root .. --pip-force-include sentencepiece
#     include $(shell uv run python -m jupytext_notebook_helper.tpmk)
#
# Generates four variants per source plus a uv bundle:
#   $(SOURCES_DIR)/<name>.py -> $(DESTDIR_TP)/<name>.ipynb         student . local
#                            -> $(DESTDIR_TP)/<name>.colab.ipynb   student . Colab (self-installs)
#                            -> $(TEACHER_DIR)/<name>.ipynb         teacher . local (solutions)
#                            -> $(TEACHER_DIR)/<name>.colab.ipynb   teacher . Colab
#                            +  $(ZIP) = pyproject + uv.lock + local notebooks + README
#
# Optional `make solution` adds a student-facing corrigé (solutions kept, but no
# instructor cells / [[...]] markers / tag comments):
#   $(SOURCES_DIR)/<name>.py -> $(SOLUTION_DIR)/<name>.ipynb         solution . local
#                            -> $(SOLUTION_DIR)/<name>.colab.ipynb   solution . Colab
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
STUDENT_BASE_DEPS     ?= jupyter jupyterlab ipywidgets
BUNDLE_PYPROJECT      ?= $(STUDENT_ENV_DIR)/pyproject.toml
BUNDLE_LOCK           ?= $(STUDENT_ENV_DIR)/uv.lock
# Passed to the filter for the Colab install cell; --uv-root tells it where
# uv.lock/pyproject.toml live (relative to the build dir).
PIP_ARGS       ?= --uv-root $(ROOT)

FILTER := $(PYTHON) python -m jupytext_notebook_helper.filter --src-root $(SRC_ROOT)
RUN    := $(PYTHON) python -m jupytext_notebook_helper.run --src-root $(SRC_ROOT)

PY_NOTEBOOKS  := $(wildcard $(SOURCES_DIR)/*.py)
NAMES         := $(patsubst $(SOURCES_DIR)/%.py,%,$(PY_NOTEBOOKS))
STUDENT_LOCAL := $(NAMES:%=$(DESTDIR_TP)/%.ipynb)
STUDENT_COLAB := $(NAMES:%=$(DESTDIR_TP)/%.colab.ipynb)
TEACHER_LOCAL := $(NAMES:%=$(TEACHER_DIR)/%.ipynb)
TEACHER_COLAB := $(NAMES:%=$(TEACHER_DIR)/%.colab.ipynb)
SOLUTION_LOCAL := $(NAMES:%=$(SOLUTION_DIR)/%.ipynb)
SOLUTION_COLAB := $(NAMES:%=$(SOLUTION_DIR)/%.colab.ipynb)
DEPFILES      := $(NAMES:%=$(DEPDIR)/%.d)
TESTED        := $(NAMES:%=$(TESTED_DIR)/%.tested)
RESOLVED      := $(NAMES:%=$(RESOLVED_DIR)/%.resolved)

.PHONY: help all student notebooks teacher solution bundle check check-raw \
	check-bundle show-tests show-raw clean
help:
	@echo "Practicals targets:"
	@echo "  student          student notebooks (local + Colab) + uv zip"
	@echo "  teacher          teacher notebooks (local + Colab, with solutions)"
	@echo "  solution         student-facing solution / corrigé (local + Colab, with"
	@echo "                   solutions, no instructor cells/markers/tag comments)"
	@echo "  bundle           the uv-ready student zip only"
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
	@echo "  clean            remove generated notebooks, teacher/, zip, $(DEPDIR), $(TESTED_DIR)"
	@echo ""
	@echo "Sources: $(NAMES)"

all: student teacher
student: $(STUDENT_LOCAL) $(STUDENT_COLAB) $(ZIP)
notebooks: student  # backward-compatible alias
teacher: $(TEACHER_LOCAL) $(TEACHER_COLAB)
solution: $(SOLUTION_LOCAL) $(SOLUTION_COLAB)
bundle: $(ZIP)

# student . Colab — auto `%pip install` cell, no solutions, drop not-colab.
$(DESTDIR_TP)/%.colab.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(DESTDIR_TP)
	$(FILTER) --depdir $(DEPDIR) --colab --exclude teacher,not-colab $(PIP_ARGS) $< > $@ || rm -f "$@"

# student . local — no install cell, no solutions.
$(DESTDIR_TP)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(DESTDIR_TP)
	$(FILTER) --depdir $(DEPDIR) --exclude teacher,colab,pip $< > $@ || rm -f "$@"

# teacher . Colab — solutions + auto `%pip install` cell (no not-colab helper).
$(TEACHER_DIR)/%.colab.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(TEACHER_DIR)
	$(FILTER) --depdir $(DEPDIR) --colab --teacher --exclude not-colab $(PIP_ARGS) $< > $@ || rm -f "$@"

# teacher . local — solutions, instructor helper cell kept.
$(TEACHER_DIR)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(TEACHER_DIR)
	$(FILTER) --depdir $(DEPDIR) --teacher --exclude colab,pip $< > $@ || rm -f "$@"

# solution (corrigé) . Colab — solutions kept, auto `%pip install` cell, but no
# instructor content: teacher-tagged cells dropped, no tag comments, no markers.
$(SOLUTION_DIR)/%.colab.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(SOLUTION_DIR)
	$(FILTER) --depdir $(DEPDIR) --colab --solution --exclude teacher,not-colab $(PIP_ARGS) $< > $@ || rm -f "$@"

# solution (corrigé) . local — solutions kept, no install cell, no instructor content.
$(SOLUTION_DIR)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(SOLUTION_DIR)
	$(FILTER) --depdir $(DEPDIR) --solution --exclude teacher,colab,pip $< > $@ || rm -f "$@"

# Generated student env: union of the per-notebook package manifests (written by
# the filter into $(DEPDIR)/<name>.pkgs while building the Colab variant) + a small
# base to run notebooks. Depends on the Colab notebooks so the manifests exist.
$(STUDENT_ENV_DIR)/pyproject.toml: $(STUDENT_COLAB)
	@mkdir -p $(STUDENT_ENV_DIR)
	@{ \
	  echo '[project]'; \
	  echo 'name = "$(STUDENT_ENV_NAME)"'; \
	  echo 'version = "0.1.0"'; \
	  echo 'requires-python = "$(STUDENT_REQUIRES_PYTHON)"'; \
	  echo 'dependencies = ['; \
	  { cat $(DEPDIR)/*.pkgs 2>/dev/null; printf '%s\n' $(STUDENT_BASE_DEPS); } \
	    | sort -u | sed 's/.*/    "&",/'; \
	  echo ']'; \
	  echo ''; \
	  echo '[tool.uv]'; \
	  echo 'package = false'; \
	} > $@
	@echo "Generated $@ from notebook imports ($(DEPDIR)/*.pkgs + base)"

$(STUDENT_ENV_DIR)/uv.lock: $(STUDENT_ENV_DIR)/pyproject.toml
	cd $(STUDENT_ENV_DIR) && uv lock

# Self-contained uv bundle for local student use.
$(ZIP): $(STUDENT_LOCAL) $(BUNDLE_PYPROJECT) $(BUNDLE_LOCK) $(STUDENT_README)
	@rm -rf $(BUNDLE_DIR)
	@mkdir -p $(BUNDLE_DIR)/notebooks $(dir $(ZIP))
	cp $(BUNDLE_PYPROJECT) $(BUNDLE_DIR)/pyproject.toml
	cp $(BUNDLE_LOCK) $(BUNDLE_DIR)/uv.lock
	cp $(STUDENT_LOCAL) $(BUNDLE_DIR)/notebooks/
	cp $(STUDENT_README) $(BUNDLE_DIR)/README.md
	rm -f $(ZIP)
	cd $(BUNDLE_DIR) && zip -r -q $(abspath $(ZIP)) . && cd -
	@rm -rf $(BUNDLE_DIR)
	@echo "Built $(ZIP)"

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

clean:
	@rm -rf $(TEACHER_DIR) $(SOLUTION_DIR) $(DEPDIR) $(TESTED_DIR) $(RESOLVED_DIR) \
		$(BUNDLE_DIR) $(STUDENT_ENV_DIR) $(STUDENT_LOCAL) $(STUDENT_COLAB) $(ZIP)

# ---- bookkeeping ----
# Auto-dependency files (listing the internal src/ modules inlined into each
# notebook) are written as a side effect of the filter (--depdir) and only
# *included* to add extra prerequisites — they are NOT prerequisites themselves
# (otherwise rewriting them on each build would make the build non-idempotent).
$(DEPDIR): ; @mkdir -p $@
$(TESTED_DIR): ; @mkdir -p $@
$(RESOLVED_DIR): ; @mkdir -p $@
-include $(wildcard $(DEPFILES))
