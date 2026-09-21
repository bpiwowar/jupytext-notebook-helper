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
#     student-base-deps = ["cs-lab>=1.0"]
#
# Generates four variants per source plus a uv bundle. Every output directory
# has one sub-directory per variant, `$(LOCAL_SUBDIR)/` and `$(COLAB_SUBDIR)/`
# (before 2.0 the local notebooks sat at its root — see `clean` below):
#   $(SOURCES_DIR)/<name>.py -> $(DESTDIR_TP)/local/<name>.ipynb    student . local
#                            -> $(DESTDIR_TP)/colab/<name>.ipynb    student . Colab (self-installs)
#                            -> $(TEACHER_DIR)/local/<name>.ipynb   teacher . local (solutions)
#                            -> $(TEACHER_DIR)/colab/<name>.ipynb   teacher . Colab
#                            +  $(ZIP) = pyproject + uv.lock + local notebooks + README
#                                       (BUNDLE_NOTEBOOKS=no drops the notebooks,
#                                        BUNDLE_EXTRA adds files at the zip root)
#   The zip only ever carries the *local* notebooks: it ships a pinned uv env, so
#   the self-installing Colab variants would be redundant there.
#
# Optional `make solution` adds a student-facing corrigé (solutions kept, but no
# instructor cells / [[...]] markers / tag comments):
#   $(SOURCES_DIR)/<name>.py -> $(SOLUTION_DIR)/local/<name>.ipynb  solution . local
#                            -> $(SOLUTION_DIR)/colab/<name>.ipynb  solution . Colab
#                            +  $(SOLUTION_ZIP) = the same uv bundle, solution
#                                       notebooks in place of the student ones
#                                       (only when SOLUTION_ZIP is set)
#
# A course may also publish the student tree to a public git repository
# (GIT_PUBLISH_URL, `make publish-git`): a student clones it and pulls the
# updates, and — on GitHub — the Colab notebooks open in Colab from it, which
# no .ipynb served over plain HTTPS can do.
#
# What is handed out, and what of it comes with its corrigé, is written in each
# source's own header (see jupytext_notebook_helper.selection):
#     publish: no     the practical is built for the teacher and run by `check`,
#                     but reaches no student — no notebook under $(DESTDIR_TP),
#                     no entry in the bundle, the index page or the manifest
#     solution: yes   its corrigé is released; `solution: no` holds it back
# PUBLISH_SOLUTIONS (default no) is what a header that says nothing means, so a
# course still releases every corrigé at once by flipping it — and a single one
# early by writing `solution: yes` in that practical alone. `make show-selection`
# prints the result. Whatever is not released stays off the server: `make rsync`
# keeps $(SOLUTION_ZIP) and $(SOLUTION_DIR) away, and `make manifest` does not
# list them. Both only concern files that live under $(DESTDIR_TP) — the
# directory that is deployed — e.g.
#     SOLUTION_DIR := $(DESTDIR_TP)/solution
#     SOLUTION_ZIP := $(DESTDIR_TP)/tp-mycourse-uv-solution.zip
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
# Sub-directories (of each of the three output directories above) holding the
# local and the Colab variants, e.g. student/local/<name>.ipynb and
# student/colab/<name>.ipynb. Neither may be empty, and they must differ.
LOCAL_SUBDIR   ?= local
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
# Second bundle, with the solution notebooks ($(SOLUTION_DIR), local variants).
# Empty: not built.
SOLUTION_ZIP          ?=
# Whether a corrigé is released (deployed by `rsync`, listed by `manifest`)
# when its source's header does not say. A header always wins, so a practical
# can be released alone (`solution: yes`) or held back (`solution: no`).
PUBLISH_SOLUTIONS     ?= no
# The index page handed to the students, at the root of $(DESTDIR_TP) — see the
# `index` target below. INDEX_TITLE is the switch: empty means no page.
INDEX_TITLE           ?=
# Where it is written. It must stay inside $(DESTDIR_TP): the links are relative
# to it, and it is deployed with the notebooks.
INDEX_HTML            ?= $(DESTDIR_TP)/index.html
# An HTML fragment inserted under the title (what the course is, which Python,
# where to ask for help). Inserted verbatim — it is the course's own file.
INDEX_INTRO           ?=
# A line at the bottom of the page, and the page's language tag.
INDEX_FOOTER          ?=
INDEX_LANG            ?= en
# How the archives are named on the page. Empty keeps the index's own wording
# ("Notebooks and environment" / "Solutions").
INDEX_STUDENT_LABEL   ?=
INDEX_SOLUTION_LABEL  ?=
# The manifest the page is built from: a build artifact, not for the server.
INDEX_MANIFEST        ?= $(BUNDLE_DIR)/index-manifest.json
# Passed to the filter for the Colab install cell; --uv-root tells it where
# uv.lock/pyproject.toml live (relative to the build dir). Append
# --pip-exclude / --pip-force-include to change *what* is installed, and
# --pip-relax to keep a package on the line but without its `==x.y.*` pin
# (for what the hosted runtime preinstalls and pins itself, e.g. numpy/torch
# on Colab). The same lists can live in the course pyproject.toml, under
# [tool.jupytext-notebook-helper].
PIP_ARGS       ?= --uv-root $(ROOT)

# `yes` unless BUNDLE_NOTEBOOKS says otherwise (no/false/0/off, any case).
ifeq ($(filter $(BUNDLE_NOTEBOOKS),no No NO false False FALSE 0 off Off OFF),)
BUNDLE_WITH_NOTEBOOKS := yes
else
BUNDLE_WITH_NOTEBOOKS :=
endif

# `yes` only if PUBLISH_SOLUTIONS says so — the safe default is to keep them
# back. This is the course-wide *default*: what a source whose header says
# nothing about its corrigé means (see $(SELECT) below, and `show-selection`).
ifneq ($(filter $(PUBLISH_SOLUTIONS),yes Yes YES true True TRUE 1 on On ON),)
SOLUTIONS_PUBLISHED := yes
else
SOLUTIONS_PUBLISHED :=
endif

# $(call under_destdir,<path>): <path> relative to $(DESTDIR_TP), or empty when
# it lies elsewhere (and so is not deployed with the notebooks, nor served from
# the manifest's base URL). Paths are compared as written: no `./` prefix.
under_destdir = $(patsubst $(DESTDIR_TP)/%,%,$(filter $(DESTDIR_TP)/%,$(1)))

RUN    := $(PYTHON) python -m jupytext_notebook_helper.run --src-root $(SRC_ROOT)

ifeq ($(strip $(COLAB_SUBDIR)),)
$(error COLAB_SUBDIR must not be empty: the Colab notebooks need their own sub-directory)
endif
ifeq ($(strip $(LOCAL_SUBDIR)),)
$(error LOCAL_SUBDIR must not be empty: the local notebooks need their own sub-directory)
endif
ifeq ($(strip $(LOCAL_SUBDIR)),$(strip $(COLAB_SUBDIR)))
$(error LOCAL_SUBDIR and COLAB_SUBDIR must differ)
endif

STUDENT_LOCAL_DIR  := $(DESTDIR_TP)/$(LOCAL_SUBDIR)
TEACHER_LOCAL_DIR  := $(TEACHER_DIR)/$(LOCAL_SUBDIR)
SOLUTION_LOCAL_DIR := $(SOLUTION_DIR)/$(LOCAL_SUBDIR)
STUDENT_COLAB_DIR  := $(DESTDIR_TP)/$(COLAB_SUBDIR)
TEACHER_COLAB_DIR  := $(TEACHER_DIR)/$(COLAB_SUBDIR)
SOLUTION_COLAB_DIR := $(SOLUTION_DIR)/$(COLAB_SUBDIR)

# The filter writes $(DEPDIR)/<name>.d, making every variant depend on the
# `src/` modules it inlines; it is told which paths those variants have.
FILTER := $(PYTHON) python -m jupytext_notebook_helper.filter --src-root $(SRC_ROOT) \
	$(foreach d,$(STUDENT_LOCAL_DIR) $(STUDENT_COLAB_DIR) $(TEACHER_LOCAL_DIR) \
		$(TEACHER_COLAB_DIR) $(SOLUTION_LOCAL_DIR) $(SOLUTION_COLAB_DIR),--dep-target "$(d)")

PY_NOTEBOOKS  := $(wildcard $(SOURCES_DIR)/*.py)
NAMES         := $(patsubst $(SOURCES_DIR)/%.py,%,$(PY_NOTEBOOKS))

# What each source's own header says: `publish: no` keeps a practical out of
# everything students see, `solution: yes|no` decides its corrigé one by one
# (see jupytext_notebook_helper.selection). Both lists come back from a single
# process at parse time — `P:<name>` for published, `S:<name>` for a released
# corrigé — rather than from a generated makefile there would then be a rule
# to keep fresh.
#
# $(NAMES) stays the whole of $(SOURCES_DIR): the teacher notebooks and
# `check` cover every source, published or not. A practical held back must not
# be a practical left to rot.
SELECT := $(PYTHON) python -m jupytext_notebook_helper.selection \
	--sources $(SOURCES_DIR) --solutions-default $(if $(SOLUTIONS_PUBLISHED),yes,no)
SELECTION       := $(shell $(SELECT) --format tags)
PUBLISHED_NAMES := $(patsubst P:%,%,$(filter P:%,$(SELECTION)))
SOLUTION_NAMES  := $(patsubst S:%,%,$(filter S:%,$(SELECTION)))
HELD_BACK_NAMES := $(filter-out $(PUBLISHED_NAMES),$(NAMES))
# `yes` when at least one corrigé is released: what used to be
# PUBLISH_SOLUTIONS alone now also depends on what the headers say.
SOLUTIONS_RELEASED := $(if $(strip $(SOLUTION_NAMES)),yes,)

STUDENT_LOCAL := $(PUBLISHED_NAMES:%=$(STUDENT_LOCAL_DIR)/%.ipynb)
STUDENT_COLAB := $(PUBLISHED_NAMES:%=$(STUDENT_COLAB_DIR)/%.ipynb)
TEACHER_LOCAL := $(NAMES:%=$(TEACHER_LOCAL_DIR)/%.ipynb)
TEACHER_COLAB := $(NAMES:%=$(TEACHER_COLAB_DIR)/%.ipynb)
SOLUTION_LOCAL := $(SOLUTION_NAMES:%=$(SOLUTION_LOCAL_DIR)/%.ipynb)
SOLUTION_COLAB := $(SOLUTION_NAMES:%=$(SOLUTION_COLAB_DIR)/%.ipynb)
# Older output names, removed by `clean` so an upgraded checkout does not keep
# serving stale notebooks: <name>.colab.ipynb (before 0.8) and <name>.ipynb at
# the root of an output directory (before 2.0).
LEGACY_OUTPUTS := $(foreach d,$(DESTDIR_TP) $(TEACHER_DIR) $(SOLUTION_DIR), \
                    $(NAMES:%=$(d)/%.colab.ipynb) $(NAMES:%=$(d)/%.ipynb))
DEPFILES      := $(NAMES:%=$(DEPDIR)/%.d)
TESTED        := $(NAMES:%=$(TESTED_DIR)/%.tested)
RESOLVED      := $(NAMES:%=$(RESOLVED_DIR)/%.resolved)

.PHONY: all student notebooks teacher solution bundle check check-raw \
	check-bundle show-tests show-raw show-selection lab lab-test clean

# `help` used to be the first target here, and so the default goal; it now sits
# at the bottom, one section per kind of work, so say it explicitly — unless the
# project declared a target of its own before the include.
ifeq ($(.DEFAULT_GOAL),)
.DEFAULT_GOAL := help
endif

# The corrigé bundle only exists once a corrigé is released; asking for it
# otherwise would archive the env under a name that promises solutions.
SOLUTION_ZIP_BUILT := $(if $(SOLUTIONS_RELEASED),$(SOLUTION_ZIP))

# $(call prune_stale,<directory>,<names kept>): remove the notebooks of
# practicals that directory is no longer meant to hold. A `publish: no` added
# to a header is otherwise invisible — the file built last week stays on disk,
# and rsync keeps serving it.
define prune_stale
	@for f in $(1)/*.ipynb; do \
		[ -e "$$f" ] || continue; \
		stem=$$(basename "$$f" .ipynb); \
		case " $(2) " in \
			*" $$stem "*) ;; \
			*) echo "  $$f: no longer handed out, removing"; rm -f "$$f";; \
		esac; \
	done
endef

all: student teacher
student: $(STUDENT_LOCAL) $(STUDENT_COLAB) $(ZIP)
	$(call prune_stale,$(STUDENT_LOCAL_DIR),$(PUBLISHED_NAMES))
	$(call prune_stale,$(STUDENT_COLAB_DIR),$(PUBLISHED_NAMES))
notebooks: student  # backward-compatible alias
teacher: $(TEACHER_LOCAL) $(TEACHER_COLAB)
solution: $(SOLUTION_LOCAL) $(SOLUTION_COLAB) $(SOLUTION_ZIP_BUILT)
	$(call prune_stale,$(SOLUTION_LOCAL_DIR),$(SOLUTION_NAMES))
	$(call prune_stale,$(SOLUTION_COLAB_DIR),$(SOLUTION_NAMES))
bundle: $(ZIP) $(SOLUTION_ZIP_BUILT)

# Each variant has its own directory, so the patterns below never compete.
# Every recipe creates its own directory with `mkdir -p $(@D)`.

# student . Colab — auto `%pip install` cell, no solutions, drop not-colab.
$(STUDENT_COLAB_DIR)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(@D)
	$(FILTER) --depdir $(DEPDIR) --colab --exclude teacher,not-colab $(PIP_ARGS) $< > $@ || rm -f "$@"

# student . local — no install cell, no solutions.
$(STUDENT_LOCAL_DIR)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(@D)
	$(FILTER) --depdir $(DEPDIR) --exclude teacher,colab,pip $< > $@ || rm -f "$@"

# teacher . Colab — solutions + auto `%pip install` cell (no not-colab helper).
$(TEACHER_COLAB_DIR)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(@D)
	$(FILTER) --depdir $(DEPDIR) --colab --teacher --exclude not-colab $(PIP_ARGS) $< > $@ || rm -f "$@"

# teacher . local — solutions, instructor helper cell kept.
$(TEACHER_LOCAL_DIR)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(@D)
	$(FILTER) --depdir $(DEPDIR) --teacher --exclude colab,pip $< > $@ || rm -f "$@"

# solution (corrigé) . Colab — solutions kept, auto `%pip install` cell, but no
# instructor content: teacher-tagged cells dropped, no tag comments, no markers.
$(SOLUTION_COLAB_DIR)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
	@mkdir -p $(@D)
	$(FILTER) --depdir $(DEPDIR) --colab --solution --exclude teacher,not-colab $(PIP_ARGS) $< > $@ || rm -f "$@"

# solution (corrigé) . local — solutions kept, no install cell, no instructor content.
$(SOLUTION_LOCAL_DIR)/%.ipynb: $(SOURCES_DIR)/%.py | $(DEPDIR)
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

# Self-contained uv bundle: pyproject + uv.lock + README (+ $(BUNDLE_EXTRA)),
# and the local notebooks given — never the self-installing Colab variants,
# which a pinned uv env makes redundant. Each archive is staged in its own
# directory, so that `make -j` can build both at once.
#   $(call build_bundle,<zip>,<notebooks, empty for none>)
define build_bundle
	@rm -rf $(BUNDLE_DIR)/$(notdir $(1))
	@mkdir -p $(BUNDLE_DIR)/$(notdir $(1)) $(dir $(1))
	cp $(BUNDLE_PYPROJECT) $(BUNDLE_DIR)/$(notdir $(1))/pyproject.toml
	cp $(BUNDLE_LOCK) $(BUNDLE_DIR)/$(notdir $(1))/uv.lock
	cp $(STUDENT_README) $(BUNDLE_DIR)/$(notdir $(1))/README.md
	$(if $(2),@mkdir -p $(BUNDLE_DIR)/$(notdir $(1))/notebooks)
	$(if $(2),cp $(2) $(BUNDLE_DIR)/$(notdir $(1))/notebooks/)
	$(if $(BUNDLE_EXTRA),cp $(BUNDLE_EXTRA) $(BUNDLE_DIR)/$(notdir $(1))/)
	rm -f $(1)
	# `ZIP=` first: make exports a variable set on ITS command line, and zip
	# reads $ZIP as its own default options — `make ZIP=out/tp.zip` would then
	# hand zip a second output file and fail there rather than here.
	cd $(BUNDLE_DIR)/$(notdir $(1)) && ZIP= zip -r -q $(abspath $(1)) . && cd -
	@rm -rf $(BUNDLE_DIR)/$(notdir $(1))
	@echo "Built $(1)$(if $(2),, (no notebooks))"
endef

BUNDLE_DEPS := $(BUNDLE_PYPROJECT) $(BUNDLE_LOCK) $(STUDENT_README) $(BUNDLE_EXTRA)

# The student bundle. The notebooks are only a prerequisite when they are
# actually shipped (BUNDLE_NOTEBOOKS): otherwise the archive is env-only and
# must stay stable while the notebooks are edited.
BUNDLE_NOTEBOOK_DEPS := $(if $(BUNDLE_WITH_NOTEBOOKS),$(STUDENT_LOCAL))

$(ZIP): $(BUNDLE_NOTEBOOK_DEPS) $(BUNDLE_DEPS)
	$(call build_bundle,$@,$(BUNDLE_NOTEBOOK_DEPS))

# The solution bundle: the same env, with the corrigé. BUNDLE_NOTEBOOKS does not
# apply — an env-only archive is the student one.
ifneq ($(strip $(SOLUTION_ZIP)),)
$(SOLUTION_ZIP): $(SOLUTION_LOCAL) $(BUNDLE_DEPS)
	$(call build_bundle,$@,$(SOLUTION_LOCAL))
endif

# Resolution test for the bundle: unzip and verify `uv` can resolve the env from
# the shipped pyproject + uv.lock — WITHOUT installing anything (`uv lock --check`).
# Catches e.g. stray editable/path deps that only exist on the instructor's machine.
check-bundle: $(ZIP) $(SOLUTION_ZIP_BUILT)
	@for zip in $^; do \
		tmp=$$(mktemp -d); \
		unzip -q $$zip -d $$tmp; \
		echo "Checking uv resolution of $$zip ..."; \
		if (cd $$tmp && uv lock --check) >/dev/null 2>$$tmp/err; then \
			echo "  PASS: bundle resolves (uv.lock consistent with pyproject)"; rm -rf $$tmp; \
		else \
			echo "  FAIL: bundle does not resolve:"; sed 's/^/    /' $$tmp/err; rm -rf $$tmp; exit 1; \
		fi; \
	done

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

# What of $(SOURCES_DIR) reaches the students, and what stays back — the
# headers' `publish:` / `solution:` keys, read the way the build reads them.
show-selection:
	@printf "  %-40s %s\n" "source" "state"
	@printf "  %-40s %s\n" "------" "-----"
	@$(SELECT) --format report
	@echo
	@echo "  publish: no  in a source's header keeps it out (it is still built"
	@echo "  for the teacher and still run by 'make check'); solution: yes|no"
	@echo "  overrides PUBLISH_SOLUTIONS (now: $(PUBLISH_SOLUTIONS)) for that one."

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
# $(LAB_DIR) defaults to $(TEACHER_LOCAL_DIR): only the teacher variant keeps the
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
LAB_DIR       ?= $(TEACHER_LOCAL_DIR)
LAB           ?= $(PYTHON) jupyter lab
LAB_PROFILE   ?= small

lab: $(TEACHER_LOCAL)
	$(LAB) $(LAB_DIR)

lab-test: $(TEACHER_LOCAL)
	NOTEBOOK_PROFILE=$(LAB_PROFILE) $(NOTEBOOK_ENV) $(LAB) $(LAB_DIR)

# $(LEGACY_OUTPUTS): notebooks at their pre-2.0 (or pre-0.8) paths.
# $(TEACHER_DIR) and $(SOLUTION_DIR) go away wholesale, but $(DESTDIR_TP) is
# only cleaned file by file (it is often a shared static/ directory), so the
# old student notebooks would otherwise survive the upgrade and keep being
# deployed. $(GIT_PUBLISH_DIR) is deliberately absent: it is a git clone, and
# may hold a commit that has not been pushed yet.
clean:
	@rm -rf $(TEACHER_DIR) $(SOLUTION_DIR) $(DEPDIR) $(TESTED_DIR) $(RESOLVED_DIR) \
		$(BUNDLE_DIR) $(STUDENT_ENV_DIR) $(STUDENT_LOCAL) $(STUDENT_COLAB) \
		$(STUDENT_LOCAL_DIR) $(STUDENT_COLAB_DIR) $(LEGACY_OUTPUTS) $(ZIP) $(SOLUTION_ZIP) \
		$(INDEX_HTML)

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
# keyed by profile; the stamp depends on $(TEACHER_LOCAL_DIR)/<name>.ipynb, which
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
$(RUN_STAMP_DIR)/%.$(RUN_PROFILE_LABEL): $(TEACHER_LOCAL_DIR)/%.ipynb
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
# Only defined when the course points RESOURCES_PY at a cs-lab declaration
# module (e.g. src/mycourse/resources.py); `check` then depends on it.
#
# `cs-lab cache check` reads the load_hf_* calls back out of $(SOURCES_DIR) and
# fails when the declaration no longer describes them: a model added to a
# notebook, one that stopped being loaded. It works on the AST, without
# importing, so a resource built at run time is never executed by it — hence
# the second step, which imports the module for real and builds every resource
# object: that is what catches an import error, a typo in a factory argument,
# or a section that no longer loads.
#
# For a new notebook, a skeleton to fill in:
#     cs-lab cache scan $(SOURCES_DIR) --emit <section>
RESOURCES_PY ?=
#: Dotted module path of $(RESOURCES_PY), derived from $(SRC_ROOT).
RESOURCES_MODULE ?= $(subst /,.,$(patsubst $(SRC_ROOT)/%,%,$(basename $(RESOURCES_PY))))
CS_LAB ?= $(PYTHON) cs-lab

ifneq ($(strip $(RESOURCES_PY)),)
.PHONY: check-resources
check-resources:
	@$(CS_LAB) cache check $(SOURCES_DIR) --search-path $(SRC_ROOT) \
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
#: directory it was not told to include, so the two variant directories must
#: be listed — without them the notebooks silently stop being deployed.
RSYNC_INCLUDE ?= $(LOCAL_SUBDIR)/ $(COLAB_SUBDIR)/ *.ipynb *.zip *.html
#: Relative to $(DESTDIR_TP): symlinked there as `data` and deployed with the
#: notebooks. Empty means the course ships no data directory.
RSYNC_DATA ?=
#: Bulk data (caches, corpora) deployed separately, by `rsync-data`.
STUDENT_DATA_DIR ?= student-data
SSH_STUDENT_DATA ?=
SSH_STUDENT_DATA_PATH ?=

RSYNC_DATA_LINK := $(if $(RSYNC_DATA),$(DESTDIR_TP)/data)
# The hand-out page, when the course has one: `rsync` deploys $(DESTDIR_TP),
# so it is what builds it — `student` leaves it alone.
RSYNC_INDEX := $(if $(strip $(INDEX_TITLE)),$(INDEX_HTML))
# The solutions under $(DESTDIR_TP), as rsync patterns anchored at its root.
# They come first — rsync stops at the first matching rule — as includes once
# released, as excludes before: a broad RSYNC_INCLUDE (`*.zip`, `*.ipynb`) would
# otherwise ship them early, and --delete-excluded takes them back down from a
# server they reached too soon. SOLUTION_DIR must then be a direct
# sub-directory of $(DESTDIR_TP).
SOLUTION_REL_DIR := $(call under_destdir,$(SOLUTION_DIR))
SOLUTION_REL_ZIP := $(call under_destdir,$(SOLUTION_ZIP))
RSYNC_SOLUTION_PATTERNS := $(if $(SOLUTION_REL_DIR),/$(SOLUTION_REL_DIR)/ /$(SOLUTION_REL_DIR)/**) \
                           $(if $(SOLUTION_REL_ZIP),/$(SOLUTION_REL_ZIP))
RSYNC_ARGS := $(foreach i,$(RSYNC_SOLUTION_PATTERNS),$(if $(SOLUTIONS_RELEASED),--include,--exclude) "$(i)") \
              $(foreach i,$(RSYNC_INCLUDE) $(if $(RSYNC_DATA),data/ data/*),--include "$(i)")

ifneq ($(strip $(SSH_HOST)),)
.PHONY: rsync
$(RSYNC_DATA_LINK):
	ln -sf $(RSYNC_DATA) $@

rsync: student $(if $(SOLUTIONS_RELEASED),solution) $(RSYNC_DATA_LINK) $(RSYNC_INDEX)
	@echo "=== Synchronizing student notebooks$(if $(SOLUTIONS_RELEASED), and solutions) on $(SSH_HOST) ==="
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

# ---- publish-git: the student tree in a public git repository -------------
# Only defined when the course sets GIT_PUBLISH_URL. Two things a directory of
# .ipynb files served over HTTPS cannot do: be opened in Google Colab — which
# imports a notebook from GitHub, Drive or a gist, never from a URL of its own
# choosing — and be updated in place by a student, `git pull` rather than one
# more download of the zip.
#
# The published tree mirrors $(DESTDIR_TP): $(LOCAL_SUBDIR)/, $(COLAB_SUBDIR)/
# and, once PUBLISH_SOLUTIONS says so, the corrigé; plus, unless
# GIT_PUBLISH_ENV says no, the uv environment the bundle ships (pyproject.toml,
# uv.lock, README.md, $(BUNDLE_EXTRA)) at its root, so that a clone is a working
# project: `uv sync`. That mirroring is also what makes the Colab URLs of
# `make manifest` correct, since they are built from GIT_PUBLISH_URL.
#
# `publish-git` stages and COMMITS; it never pushes. `publish-git-push` pushes,
# and does nothing else — what reaches that repository is what the students
# read, so making it public is a step of its own:
#
#     make publish-git
#     git -C $(GIT_PUBLISH_DIR) show --stat      # read it
#     make publish-git-push
#
# A git history keeps what it was given: a file published once stays in it even
# after a later run removes it from the tip — worth a thought before turning
# PUBLISH_SOLUTIONS on.
GIT_PUBLISH_URL        ?=
GIT_PUBLISH_BRANCH     ?= main
#: The working clone, kept between runs — it may hold a commit that has not
#: been pushed, so `clean` leaves it alone. Ignore it in the course's own
#: repository.
GIT_PUBLISH_DIR        ?= outputs/git-publish
#: Where the tree is staged before being mirrored into the clone.
GIT_PUBLISH_STAGE      ?= $(BUNDLE_DIR)/git-publish
#: Ship the uv environment at the root of the repository (the bundle, unzipped).
GIT_PUBLISH_ENV        ?= yes
#: Ship the notebooks themselves. Defaults to BUNDLE_NOTEBOOKS: a course that
#: hands the notebooks out one by one rather than in the archive usually means
#: it of every archive, this repository included. Set it to `yes` to publish an
#: env-only zip but a repository with the notebooks — which is what the Colab
#: links of `make manifest` need (they open a notebook from GitHub).
GIT_PUBLISH_NOTEBOOKS  ?= $(BUNDLE_NOTEBOOKS)
GIT_PUBLISH_README     ?= $(STUDENT_README)
#: More files at the root of the published tree, under their own names.
GIT_PUBLISH_EXTRA      ?=
#: Paths the mirror never adds, changes or removes: they belong to the
#: published repository itself, not to this build.
GIT_PUBLISH_PRESERVE   ?= .git .gitignore .github LICENSE
GIT_PUBLISH_CLONE_ARGS ?=
#: Recursive (`=`, not `:=`): git then runs only when a publish happens, not on
#: every make in every course.
GIT_PUBLISH_SOURCE_REV  = $(shell git rev-parse --short HEAD 2>/dev/null)
GIT_PUBLISH_MESSAGE    ?= $(if $(GIT_PUBLISH_SOURCE_REV),Update the practicals (source $(GIT_PUBLISH_SOURCE_REV)),Update the practicals)

ifeq ($(filter $(GIT_PUBLISH_ENV),no No NO false False FALSE 0 off Off OFF),)
GIT_PUBLISH_WITH_ENV := yes
else
GIT_PUBLISH_WITH_ENV :=
endif

ifeq ($(filter $(GIT_PUBLISH_NOTEBOOKS),no No NO false False FALSE 0 off Off OFF),)
GIT_PUBLISH_WITH_NOTEBOOKS := yes
else
GIT_PUBLISH_WITH_NOTEBOOKS :=
endif
# The corrigé travels only once it is released, like it does to the server.
GIT_PUBLISH_SOLUTION_REL := $(if $(GIT_PUBLISH_WITH_NOTEBOOKS),$(if $(SOLUTIONS_RELEASED),$(SOLUTION_REL_DIR)))
GIT_PUBLISH_EXCLUDES := $(foreach p,$(GIT_PUBLISH_PRESERVE),--exclude "/$(p)")

ifneq ($(strip $(GIT_PUBLISH_URL)),)
GIT_PUBLISH_ENV_FILES := $(if $(GIT_PUBLISH_WITH_ENV),\
	$(BUNDLE_PYPROJECT) $(BUNDLE_LOCK) $(GIT_PUBLISH_README) $(BUNDLE_EXTRA))
GIT_PUBLISH_NOTEBOOK_FILES := $(if $(GIT_PUBLISH_WITH_NOTEBOOKS),$(STUDENT_LOCAL) $(STUDENT_COLAB))
GIT_PUBLISH_SOLUTION_FILES := $(if $(GIT_PUBLISH_SOLUTION_REL),$(SOLUTION_LOCAL) $(SOLUTION_COLAB))
GIT_PUBLISH_SOLUTION_STAGE := $(GIT_PUBLISH_STAGE)/$(GIT_PUBLISH_SOLUTION_REL)
# The hand-out page, when the course has one: the published tree mirrors
# $(DESTDIR_TP), and its Colab links are the absolute ones built from
# $(GIT_PUBLISH_URL), so it is the same page here as on the server.
GIT_PUBLISH_INDEX := $(if $(strip $(INDEX_TITLE)),$(INDEX_HTML))

.PHONY: publish-git publish-git-push
# The notebooks are named one by one, never a directory: the `data` symlink
# `make rsync` leaves in $(DESTDIR_TP), and any .ipynb_checkpoints/, then have
# no way into the published repository.
publish-git: $(GIT_PUBLISH_NOTEBOOK_FILES) $(GIT_PUBLISH_SOLUTION_FILES) \
		$(GIT_PUBLISH_ENV_FILES) $(GIT_PUBLISH_EXTRA) $(GIT_PUBLISH_INDEX)
	@rm -rf $(GIT_PUBLISH_STAGE)
	@mkdir -p $(GIT_PUBLISH_STAGE)
	$(if $(GIT_PUBLISH_WITH_NOTEBOOKS),@mkdir -p $(GIT_PUBLISH_STAGE)/$(LOCAL_SUBDIR) $(GIT_PUBLISH_STAGE)/$(COLAB_SUBDIR))
	$(if $(GIT_PUBLISH_WITH_NOTEBOOKS),@cp $(STUDENT_LOCAL) $(GIT_PUBLISH_STAGE)/$(LOCAL_SUBDIR)/)
	$(if $(GIT_PUBLISH_WITH_NOTEBOOKS),@cp $(STUDENT_COLAB) $(GIT_PUBLISH_STAGE)/$(COLAB_SUBDIR)/)
	$(if $(GIT_PUBLISH_SOLUTION_REL),@mkdir -p $(GIT_PUBLISH_SOLUTION_STAGE)/$(LOCAL_SUBDIR) $(GIT_PUBLISH_SOLUTION_STAGE)/$(COLAB_SUBDIR))
	$(if $(GIT_PUBLISH_SOLUTION_REL),@cp $(SOLUTION_LOCAL) $(GIT_PUBLISH_SOLUTION_STAGE)/$(LOCAL_SUBDIR)/)
	$(if $(GIT_PUBLISH_SOLUTION_REL),@cp $(SOLUTION_COLAB) $(GIT_PUBLISH_SOLUTION_STAGE)/$(COLAB_SUBDIR)/)
	$(if $(GIT_PUBLISH_WITH_ENV),@cp $(BUNDLE_PYPROJECT) $(GIT_PUBLISH_STAGE)/pyproject.toml)
	$(if $(GIT_PUBLISH_WITH_ENV),@cp $(BUNDLE_LOCK) $(GIT_PUBLISH_STAGE)/uv.lock)
	$(if $(GIT_PUBLISH_WITH_ENV),@cp $(GIT_PUBLISH_README) $(GIT_PUBLISH_STAGE)/README.md)
	$(if $(GIT_PUBLISH_WITH_ENV),$(if $(BUNDLE_EXTRA),@cp $(BUNDLE_EXTRA) $(GIT_PUBLISH_STAGE)/))
	$(if $(GIT_PUBLISH_EXTRA),@cp $(GIT_PUBLISH_EXTRA) $(GIT_PUBLISH_STAGE)/)
	$(if $(GIT_PUBLISH_INDEX),@cp $(GIT_PUBLISH_INDEX) $(GIT_PUBLISH_STAGE)/)
	@set -e; \
	dir="$(GIT_PUBLISH_DIR)"; branch="$(GIT_PUBLISH_BRANCH)"; \
	if [ ! -d "$$dir/.git" ]; then \
		echo "=== Cloning $(GIT_PUBLISH_URL) into $$dir ==="; \
		git clone $(GIT_PUBLISH_CLONE_ARGS) "$(GIT_PUBLISH_URL)" "$$dir"; \
	fi; \
	git -C "$$dir" remote set-url origin "$(GIT_PUBLISH_URL)"; \
	git -C "$$dir" fetch --quiet origin; \
	if git -C "$$dir" show-ref --verify --quiet "refs/heads/$$branch"; then \
		git -C "$$dir" checkout --quiet "$$branch"; \
		if git -C "$$dir" show-ref --verify --quiet "refs/remotes/origin/$$branch"; then \
			git -C "$$dir" merge --ff-only --quiet "origin/$$branch" || \
				echo "publish-git: $$dir is ahead of origin/$$branch — left as it is"; \
		fi; \
	elif git -C "$$dir" show-ref --verify --quiet "refs/remotes/origin/$$branch"; then \
		git -C "$$dir" checkout --quiet -b "$$branch" "origin/$$branch"; \
	else \
		git -C "$$dir" symbolic-ref HEAD "refs/heads/$$branch"; \
	fi; \
	rsync -a --delete $(GIT_PUBLISH_EXCLUDES) "$(GIT_PUBLISH_STAGE)/" "$$dir/"; \
	git -C "$$dir" add -A; \
	if git -C "$$dir" diff --cached --quiet; then \
		echo "publish-git: nothing changed"; \
	else \
		git -C "$$dir" commit -q -m "$(GIT_PUBLISH_MESSAGE)"; \
		git -C "$$dir" --no-pager log --oneline -1; \
	fi; \
	if git -C "$$dir" show-ref --verify --quiet "refs/remotes/origin/$$branch"; then \
		ahead=$$(git -C "$$dir" rev-list --count "origin/$$branch..$$branch"); \
	else \
		ahead=$$(git -C "$$dir" rev-list --count "$$branch" 2>/dev/null || echo 0); \
	fi; \
	if [ "$$ahead" -gt 0 ]; then \
		echo "publish-git: $$ahead commit(s) waiting — read them with 'git -C $$dir show --stat', publish with 'make publish-git-push'"; \
	fi
	@rm -rf $(GIT_PUBLISH_STAGE)

publish-git-push:
	@test -d $(GIT_PUBLISH_DIR)/.git || { \
		echo "ERROR: no clone at $(GIT_PUBLISH_DIR) — run 'make publish-git' first"; \
		exit 1; }
	git -C $(GIT_PUBLISH_DIR) push origin $(GIT_PUBLISH_BRANCH)
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
MANIFEST_SOLUTION_LABEL       ?= Solution
MANIFEST_SOLUTION_COLAB_LABEL ?= Solution (Colab)
# Header keys (under jupyter.metadata) holding a practical's display name and
# its one-line description. A source without them keeps its file name and has
# no description.
MANIFEST_NAME_KEY        ?= practical_name
MANIFEST_DESCRIPTION_KEY ?= practical_description

# The Colab entries get an absolute URL — opening the notebook in Colab rather
# than downloading it — as soon as the course publishes to a public GitHub
# repository ($(GIT_PUBLISH_URL), see `publish-git` above). Nothing to set here:
# the paths line up because `publish-git` mirrors $(DESTDIR_TP), and a second
# place to write the URL is a second place for it to go stale. A repository
# elsewhere than GitHub leaves the entries relative, with a word on stderr —
# Colab imports from GitHub, Drive or a gist only.
# Nothing to open in Colab when the repository carries no notebooks
# (GIT_PUBLISH_NOTEBOOKS), so the entries then stay relative.
MANIFEST_COLAB_GIT_ARGS = $(if $(GIT_PUBLISH_WITH_NOTEBOOKS),$(if $(strip $(GIT_PUBLISH_URL)),\
	--colab-git-url "$(GIT_PUBLISH_URL)" --colab-git-branch "$(GIT_PUBLISH_BRANCH)"))

# The archives and, once PUBLISH_SOLUTIONS says so, the solutions: whatever of
# them lives under $(DESTDIR_TP), so is served from the same base URL. Held in
# variables rather than written inline: a `$(if ...)` argument is cut at its
# first comma, and a label may well have one.
MANIFEST_BUNDLE_ARGS := \
	$(if $(call under_destdir,$(ZIP)),--bundle "student=$(call under_destdir,$(ZIP))") \
	$(if $(SOLUTIONS_RELEASED),$(if $(SOLUTION_REL_ZIP),--bundle "solution=$(SOLUTION_REL_ZIP)"))
MANIFEST_SOLUTION_ARGS = --solution-subdir "$(SOLUTION_REL_DIR)" \
	--solution-label "$(MANIFEST_SOLUTION_LABEL)" \
	--solution-colab-label "$(MANIFEST_SOLUTION_COLAB_LABEL)" \
	--solutions-default $(if $(SOLUTIONS_PUBLISHED),yes,no)

# What describes the practicals, whoever the reader is. `manifest` adds the
# base URL of its own reader; `index` (below) writes the same list for a reader
# sitting in $(DESTDIR_TP) itself, so it adds nothing.
MANIFEST_COMMON_ARGS = --sources $(SOURCES_DIR) --local-subdir "$(LOCAL_SUBDIR)" \
	--colab-subdir "$(COLAB_SUBDIR)" --name-key "$(MANIFEST_NAME_KEY)" \
	--description-key "$(MANIFEST_DESCRIPTION_KEY)" \
	--local-label "$(MANIFEST_LOCAL_LABEL)" \
	--colab-label "$(MANIFEST_COLAB_LABEL)" \
	$(MANIFEST_COLAB_GIT_ARGS) \
	$(MANIFEST_BUNDLE_ARGS) \
	$(if $(SOLUTION_REL_DIR),$(MANIFEST_SOLUTION_ARGS))

.PHONY: manifest
manifest:
	@test -n "$(MANIFEST)" || { \
		echo "ERROR: MANIFEST is not set — name the file to write, e.g."; \
		echo "       make manifest MANIFEST=../slides/practicals.json"; \
		exit 1; }
	@$(PYTHON) python -m jupytext_notebook_helper.manifest \
		$(MANIFEST_COMMON_ARGS) --output $(MANIFEST) \
		$(if $(MANIFEST_BASE_URL),--base-url "$(MANIFEST_BASE_URL)") \
		$(if $(MANIFEST_RELATIVE_TO),--deploy-path "$(if $(strip $(SSH_HOST)),$(strip $(SSH_HOST)):)$(SSH_PATH)" \
			--relative-to "$(MANIFEST_RELATIVE_TO)")

# ---- index.html: the page that hands the practicals out -------------------
# A directory listing is not a hand-out — it shows every .ipynb, the zip and
# the variant directories in server order, with no word on what to open first.
# Setting INDEX_TITLE turns on an index page written at the root of
# $(DESTDIR_TP), from the same description `manifest` writes: the archives to
# download, then one row per practical (name, description, one link per
# variant).
#
# `make index` builds it, and so do the two targets that publish it, `rsync`
# and `publish-git`. `student` does NOT: the page is about handing the
# notebooks out, not about building them, and a course that wants it on every
# build says so in one line:
#
#     student: index
#
#     INDEX_TITLE := Reinforcement learning — practicals
#     INDEX_INTRO := sources/index-intro.html   # a fragment, inserted verbatim
#
INDEX_ZIPS := $(ZIP) $(if $(SOLUTIONS_RELEASED),$(SOLUTION_ZIP))
# Held in a variable rather than written inline: a `$(if ...)` argument is cut
# at its first comma, and a label may well have one.
INDEX_LABEL_ARGS := \
	$(if $(INDEX_STUDENT_LABEL),--bundle-label "student=$(INDEX_STUDENT_LABEL)") \
	$(if $(INDEX_SOLUTION_LABEL),--bundle-label "solution=$(INDEX_SOLUTION_LABEL)")

.PHONY: index
index: $(INDEX_HTML)

# Rebuilt when a source header changes (the names and descriptions), when the
# introduction does, or when an archive does (its size is on the page). The
# page itself is only rewritten when its bytes change, so an unchanged course
# leaves the file — and everything keyed off its timestamp — alone.
$(INDEX_HTML): $(PY_NOTEBOOKS) $(INDEX_INTRO) $(INDEX_ZIPS)
	@test -n "$(INDEX_TITLE)" || { \
		echo "ERROR: INDEX_TITLE is not set — name the page, e.g."; \
		echo "       INDEX_TITLE := Reinforcement learning — practicals"; \
		exit 1; }
	@mkdir -p $(@D)
	@$(PYTHON) python -m jupytext_notebook_helper.manifest \
		$(MANIFEST_COMMON_ARGS) --output $(INDEX_MANIFEST) >/dev/null
	@$(PYTHON) python -m jupytext_notebook_helper.index \
		--manifest $(INDEX_MANIFEST) --output $@ \
		--title "$(INDEX_TITLE)" --lang "$(INDEX_LANG)" \
		$(if $(INDEX_INTRO),--intro "$(INDEX_INTRO)") \
		$(if $(INDEX_FOOTER),--footer "$(INDEX_FOOTER)") \
		$(INDEX_LABEL_ARGS)

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
                   $(SOURCES_DIR)/ (cs-lab cache check), then import it for real
                   and build every resource. Run by 'check'. A skeleton for a
                   new notebook: cs-lab cache scan $(SOURCES_DIR) --emit <section>
endef

define HELP_RSYNC
  rsync            deploy $(DESTDIR_TP)/ to $(SSH_HOST):$(SSH_PATH)
                   (solutions too with PUBLISH_SOLUTIONS=yes, now: $(PUBLISH_SOLUTIONS))
endef

define HELP_RSYNC_DATA
  rsync-data       deploy $(STUDENT_DATA_DIR)/ to $(SSH_STUDENT_DATA)
endef

define HELP_PUBLISH_GIT
  publish-git      mirror $(DESTDIR_TP)/ into a clone of $(GIT_PUBLISH_URL)
                   ($(GIT_PUBLISH_DIR)) and commit — it never pushes
                   (solutions too with PUBLISH_SOLUTIONS=yes, now: $(PUBLISH_SOLUTIONS))
  publish-git-push push $(GIT_PUBLISH_BRANCH) there, and nothing else
endef

define HELP_TEXT

Build
  student          student notebooks (local + Colab) + uv zip
  teacher          teacher notebooks (local + Colab, with solutions)
  solution         student-facing solution / corrigé (local + Colab, with
                   solutions, no instructor cells/markers/tag comments)$(if $(SOLUTION_ZIP),
                   + $(SOLUTION_ZIP))
  bundle           the uv-ready zip(s) only$(if $(BUNDLE_WITH_NOTEBOOKS),, (student: env only, no notebooks))
  all              student + teacher
  index            the hand-out page at $(INDEX_HTML): the archives to
                   download, then one row per practical with a link per
                   variant.$(if $(strip $(INDEX_TITLE)), Built by 'rsync' and 'publish-git'; not by
                   'student' — add 'student: index' to build it there too., Set INDEX_TITLE to turn it on.)
  manifest         JSON description of the practicals (ids, names, files, URL)
                   for whatever announces them — reads the headers only, builds
                   no notebook. Needs MANIFEST=<file>; MANIFEST_BASE_URL or
                   MANIFEST_RELATIVE_TO says where they are served from.
                   A practical says in its own header whether it is listed
                   ('publish:') and whether its corrigé is ('solution:').
  outline          per-notebook table of contents (headers + print_header())
                   with each [[student]]/[[assert]] marker nested under its
                   section — reads the sources only, builds no notebook.
                     OUTLINE_NAMES=<name> [<name> ...]  restrict to these
  clean            remove generated notebooks, $(TEACHER_DIR)/, zip, $(DEPDIR), $(TESTED_DIR)

What is handed out
  show-selection   which practicals are published, and which release their
                   corrigé — from each source's own header ('publish:',
                   'solution:'), with PUBLISH_SOLUTIONS (now: $(PUBLISH_SOLUTIONS)) as the
                   default for a header that says nothing.$(if $(HELD_BACK_NAMES),
                   Held back right now: $(HELD_BACK_NAMES).)

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
                   figures still shown$(if $(or $(SSH_HOST),$(SSH_STUDENT_DATA),$(GIT_PUBLISH_URL)),

Deploy)$(if $(SSH_HOST),
$(HELP_RSYNC))$(if $(SSH_STUDENT_DATA),
$(HELP_RSYNC_DATA))$(if $(GIT_PUBLISH_URL),
$(HELP_PUBLISH_GIT))
endef
export HELP_TEXT

define HELP_FOOTER

Layout: $(LOCAL_SUBDIR)/<name>.ipynb and $(COLAB_SUBDIR)/<name>.ipynb in each output
        directory — student: $(DESTDIR_TP), teacher: $(TEACHER_DIR),
        solution: $(SOLUTION_DIR)

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
