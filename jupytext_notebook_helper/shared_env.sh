#!/usr/bin/env bash
# A shared student environment on a remote machine, built from the release's
# uv.lock — run there by `make shared-env` (tp.mk), which first copies the
# release's pyproject.toml, uv.lock and resources.py, and this script, to
# $ROOT/incoming/$LINK/, then runs it there with `ssh HOST bash -l ...`.
#
#   ROOT/
#     bin/uv              uv, at the version the course's lock was written with
#     python/             the Pythons uv installs (one per minor version)
#     cache/              uv's cache: environments hardlink into it, so two
#                         builds share every package they have in common
#     <hash>/             one environment (a venv) per lock and Python version,
#                         plus the lock it was built from (uv.lock, which
#                         `cs-lab course` checks) and constraints.txt (for a
#                         student's own overlay)
#     current, current-dev   the environment of each site, switched atomically
#     incoming/<link>/    what `make shared-env` sends, and the build's log
#
# What an environment holds depends on its lock and its Python version only
# (`uv sync --frozen --no-install-project`: not on pyproject.toml), and its
# name is their hash: the same lock is built once, whichever site asks for it.
# What does not change the packages — the cache it points to, the resources
# to download — is redone on every run instead.
#
# Each environment sets CS_LAB_CACHE_PATH (and IR_DATASETS_HOME) for whoever
# runs its Python, unless already set: a .pth file in its site-packages.
#
# Arguments: ROOT (relative to $HOME, or absolute) LINK PYTHON CACHE UV_VERSION
# KEEP. CACHE (CS_LAB_CACHE_PATH there, relative to $HOME or absolute) may be
# empty: then nothing is downloaded. Everything is made readable by all.
#
# Robustness:
# - the build runs detached, holding a lock, its output in build.log: a
#   dropped ssh connection does not stop it, and running this again follows it;
# - a build works on its own copy of incoming/<link>/, so a deploy sending a
#   newer lock meanwhile does not change what it builds — that deploy waits for
#   it, then builds its own (at once "already built" when it is the same);
# - an environment is built under its own lock (`current` and `current-dev`
#   may ask for the same one at the same time), and is used only once complete;
# - a resource that fails to download is reported, not fatal: the notebooks
#   fetch it from the Hub, and the environment is switched anyway;
# - the locks are flock(1)s, which the kernel releases when their holder ends,
#   however it ends; the commands the build runs do not inherit them (an
#   orphaned `uv` would otherwise hold them on), and a failed build stops what
#   it started and removes the environment it left half built. A build killed
#   outright (no status written) is noticed by whoever follows it.
#
# SHARED_ENV_ACTION (environment) picks something else than a build, with the
# same arguments: `status` (the links, the environments, the builds), `log`
# (follow the running build of LINK to its end) or `clean` (what a build
# killed outright leaves: half-built environments, lock files, build copies;
# then the old environments beyond KEEP).
set -euo pipefail
umask 022

absolute() { case "$1" in /*) echo "$1" ;; *) echo "$HOME/$1" ;; esac; }

ROOT=$(absolute "$1")
LINK=$2
PYTHON=$3
CACHE=${4:+$(absolute "$4")}
UV_VERSION=$5
KEEP=${6:-3}

INCOMING=$ROOT/incoming/$LINK
LOG=$INCOMING/build.log
STATUS=$INCOMING/build.status
BUILD_LOCK=$INCOMING/build.lock

say() { echo "[shared-env] $*"; }
# Whether a lock file is held (by a running build); a missing one is not.
held() { [ -e "$1" ] && ! flock -n "$1" true; }
# Environment directories (16 hex digits), newest first.
environments() {
    (cd "$ROOT" && ls -1dt -- [0-9a-f]*/ 2>/dev/null \
        | sed 's:/$::' | grep -E '^[0-9a-f]{16}$' || true)
}
# Whether any build is running (an older version of this script took no lock
# per environment: an unfinished one may still be its).
building() {
    local lock
    for lock in "$ROOT"/incoming/*/build.lock; do
        held "$lock" && return 0
    done
    return 1
}
links_to() { # the links pointing to an environment
    local out="" link
    for link in current current-dev; do
        [ "$(readlink "$ROOT/$link" 2>/dev/null)" = "$1" ] && out="$out $link"
    done
    echo "${out# }"
}
# Old environments beyond KEEP, unused by a link and not being built.
prune() {
    local kept=0 env
    for env in $(environments); do
        [ -z "$(links_to "$env")" ] || continue
        [ -f "$ROOT/$env/.complete" ] || continue # unfinished: see clean
        kept=$((kept + 1))
        [ "$kept" -gt "$KEEP" ] || continue
        if (flock -n 7 || exit 1; rm -rf -- "${ROOT:?}/$env") 7>"$ROOT/.$env.lock"; then
            rm -f "$ROOT/.$env.lock"
            say "removed old environment $env"
        fi
    done
}
follow() { # the running build's log, until it ends; its exit status
    tail -n +1 -F "$LOG" 2>/dev/null &
    local follower=$!
    # Until it says how it ended — or ends without saying (killed).
    while [ ! -f "$STATUS" ] && held "$BUILD_LOCK"; do sleep 2; done
    sleep 1
    kill "$follower" 2>/dev/null || true
    if [ ! -f "$STATUS" ]; then
        echo "error: the build ended without a status (killed?): see $LOG" >&2
        return 1
    fi
    return "$(cat "$STATUS")"
}

case "${SHARED_ENV_ACTION:-build}" in
build) ;;
status)
    echo "$ROOT"
    for link in current current-dev; do
        printf '  %-12s -> %s\n' "$link" "$(readlink "$ROOT/$link" 2>/dev/null || echo '(none)')"
    done
    for env in $(environments); do
        if [ -f "$ROOT/$env/.complete" ]; then state=complete
        elif held "$ROOT/.$env.lock"; then state="being built"
        elif building; then state="unfinished (a build is running)"
        else state="half built (make shared-env-clean)"
        fi
        used=$(links_to "$env")
        printf '  %s  %s  %s%s\n' "$env" "$(date -r "$ROOT/$env" '+%F %R')" \
            "$state" "${used:+  <- $used}"
    done
    for dir in "$ROOT"/incoming/*/; do
        [ -d "$dir" ] || continue
        name=$(basename "$dir")
        if held "$dir/build.lock"; then state=running
        elif [ -f "$dir/build.status" ]; then state="last build: exit $(cat "$dir/build.status")"
        elif [ -s "$dir/build.log" ]; then state="last build: no status (killed?)"
        else state="never built"
        fi
        echo "  build of $name: $state"
        [ -s "$dir/build.log" ] && tail -n 3 "$dir/build.log" | sed 's/^/      /'
    done
    exit 0 ;;
log)
    if ! held "$BUILD_LOCK"; then
        say "no build of $LINK running"
        [ -s "$LOG" ] && tail -n 5 "$LOG"
        [ -f "$STATUS" ] && exit "$(cat "$STATUS")"
        exit 0
    fi
    follow; exit $? ;;
clean)
    if building; then
        say "a build is running: unfinished environments are left alone"
    else for env in $(environments); do
        if [ ! -f "$ROOT/$env/.complete" ] && \
            (flock -n 7 || exit 1; rm -rf -- "${ROOT:?}/$env") 7>"$ROOT/.$env.lock"; then
            say "removed the half-built environment $env"
        fi
    done; fi
    for lock in "$ROOT"/.[0-9a-f]*.lock; do
        [ -e "$lock" ] || continue
        env=$(basename "$lock" .lock); env=${env#.}
        [ -d "$ROOT/$env" ] || { held "$lock" || rm -f "$lock"; }
    done
    for work in "$ROOT"/incoming/.*.build; do
        [ -d "$work" ] || continue
        link=$(basename "$work" .build); link=${link#.}
        held "$ROOT/incoming/$link/build.lock" || { rm -rf -- "$work"; say "removed $work"; }
    done
    prune
    exit 0 ;;
*) echo "error: SHARED_ENV_ACTION is build, status, log or clean" >&2; exit 2 ;;
esac

for f in pyproject.toml uv.lock; do
    [ -f "$INCOMING/$f" ] || { echo "error: no $INCOMING/$f" >&2; exit 1; }
done

# ---- detached: start the build, or wait for the running one ---------------
if [ -z "${SHARED_ENV_DETACHED:-}" ]; then
    while :; do
        exec 9>"$BUILD_LOCK"
        if flock -n 9; then
            rm -f "$STATUS"
            : > "$LOG"
            # The build inherits descriptor 9, hence the lock, until it ends.
            SHARED_ENV_DETACHED=1 setsid nohup bash "$0" "$@" >"$LOG" 2>&1 </dev/null &
            exec 9>&-
            sleep 1 # the build has the lock: follow() waits while it is held
            follow
            exit $?
        fi
        exec 9>&-
        say "a build is already running (another deploy?): following it, then building this release"
        follow || true
        say "that build is done; now this release"
    done
fi

ENV=""
finish() {
    local status=$?
    trap - EXIT INT TERM HUP
    if [ "$status" -ne 0 ]; then
        # This build is its own process group (setsid): stop what it started,
        # not itself.
        trap '' TERM
        kill -TERM -- -$$ 2>/dev/null || true
        if [ -n "$ENV" ] && [ -d "$ENV" ] && [ ! -f "$ENV/.complete" ]; then
            say "removing the half-built environment $(basename "$ENV")"
            rm -rf -- "$ENV"
        fi
        say "FAILED (exit $status)"
    fi
    rm -rf -- "${WORK:-}"
    echo "$status" > "$STATUS"
    exit "$status"
}
trap finish EXIT
trap 'exit 143' INT TERM HUP
# The build holds its lock (descriptor 9) to the end; the commands it runs do
# not get it, nor the environment's (8): `8>&- 9>&-` on each.

# ---- what this build works on: a copy, which no later deploy changes ------
WORK=$ROOT/incoming/.$LINK.build
rm -rf "$WORK"
mkdir -p "$WORK"
cp "$INCOMING/pyproject.toml" "$INCOMING/uv.lock" "$WORK/"
[ -f "$INCOMING/resources.py" ] && cp "$INCOMING/resources.py" "$WORK/"

# ---- uv, the version the lock was written with --------------------------
UV=$ROOT/bin/uv
if [ ! -x "$UV" ] || [ "$("$UV" --version | cut -d' ' -f2)" != "$UV_VERSION" ]; then
    say "installing uv $UV_VERSION in $ROOT/bin"
    mkdir -p "$ROOT/bin"
    curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" 9>&- \
        | env UV_UNMANAGED_INSTALL="$ROOT/bin" sh >/dev/null 9>&-
fi
export UV_CACHE_DIR=$ROOT/cache
export UV_PYTHON_INSTALL_DIR=$ROOT/python
export UV_PYTHON_PREFERENCE=only-managed
export UV_LINK_MODE=hardlink
export UV_NO_CONFIG=1
# A room machine may reach the internet through a slow proxy.
export UV_HTTP_TIMEOUT=${UV_HTTP_TIMEOUT:-300}
export UV_CONCURRENT_DOWNLOADS=${UV_CONCURRENT_DOWNLOADS:-4}

# ---- the environment of this lock and Python ----------------------------
HASH=$({ cat "$WORK/uv.lock"; echo "python=$PYTHON"; } | sha256sum | cut -c1-16)
exec 8>"$ROOT/.$HASH.lock"
flock 8 # another site may be building the same environment
ENV=$ROOT/$HASH # from here on, the failure handler may remove it
if [ -f "$ENV/.complete" ]; then
    say "environment $HASH already built"
else
    say "building environment $HASH (Python $PYTHON)"
    rm -rf "$ENV"
    (cd "$WORK" && UV_PROJECT_ENVIRONMENT=$ENV \
        "$UV" sync --frozen --no-install-project --python "$PYTHON" 8>&- 9>&-)
    cp "$WORK/pyproject.toml" "$WORK/uv.lock" "$ENV/"
    (cd "$WORK" && "$UV" export --frozen --no-hashes --no-header \
        --no-emit-project -o "$ENV/constraints.txt" >/dev/null 8>&- 9>&-)
    "$ENV/bin/python" -c 'import cs_lab' 8>&- 9>&- \
        || { echo "error: cs_lab does not import in $ENV" >&2; exit 1; }
    touch "$ENV/.complete"
fi

# ---- where it reads the models from (on every run: not part of the hash) --
SITE=$("$ENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])' 8>&- 9>&-)
PTH=$SITE/zz_course_cache.pth
if [ -n "$CACHE" ]; then
    echo "import os; os.environ.setdefault('CS_LAB_CACHE_PATH', '$CACHE'); os.environ.setdefault('IR_DATASETS_HOME', '$CACHE/ir_datasets')" > "$PTH.tmp"
    mv "$PTH.tmp" "$PTH"
else
    rm -f "$PTH"
fi
exec 8>&-
DONE_ENV=$ENV
ENV="" # complete: a later failure must not remove it

# ---- the resources this release's notebooks load ------------------------
missing=""
if [ -n "$CACHE" ] && [ -f "$WORK/resources.py" ]; then
    say "downloading the resources into $CACHE"
    mkdir -p "$CACHE"
    if ! CS_LAB_CACHE_PATH=$CACHE IR_DATASETS_HOME=$CACHE/ir_datasets \
        "$DONE_ENV/bin/cs-lab" cache download --from "$WORK/resources.py" --keep-going 9>&-; then
        missing=yes
    fi
fi

# ---- switch, then drop the old environments -----------------------------
ln -sfn "$HASH" "$ROOT/.$LINK.tmp"
mv -T "$ROOT/.$LINK.tmp" "$ROOT/$LINK"
say "$ROOT/$LINK -> $HASH"
prune

if [ -n "$missing" ]; then
    say "WARNING: some resources could not be downloaded (above): the notebooks will fetch them from the Hub"
fi
say "done: $ROOT/$LINK (python: $ROOT/$LINK/bin/python)"
