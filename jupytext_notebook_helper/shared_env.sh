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
#     <lock hash>/        one environment per lock (a venv), plus the lock it
#                         was built from (uv.lock, which `cs-lab course` checks),
#                         constraints.txt (for a student's own overlay) and
#                         resources.py
#     current, current-dev   the environment of each site, switched atomically
#
# Each environment sets CS_LAB_CACHE_PATH (and IR_DATASETS_HOME) for whoever
# runs its Python, unless already set: a .pth file in its site-packages.
#
# Arguments: ROOT (relative to $HOME, or absolute) LINK PYTHON CACHE UV_VERSION
# KEEP. CACHE (CS_LAB_CACHE_PATH there, relative to $HOME or absolute) may be
# empty: then nothing is downloaded. Everything is made readable by all.
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
for f in pyproject.toml uv.lock; do
    [ -f "$INCOMING/$f" ] || { echo "error: no $INCOMING/$f" >&2; exit 1; }
done

# ---- detached: a dropped ssh connection must not kill a long build ------
# The build runs in the background, holding a lock, its output in build.log;
# this only follows the log and returns its exit status. Run again while it is
# still going, it follows the same build instead of starting another.
LOG=$INCOMING/build.log
STATUS=$INCOMING/build.status
if [ -z "${SHARED_ENV_DETACHED:-}" ]; then
    exec 9>"$INCOMING/build.lock"
    if flock -n 9; then
        rm -f "$STATUS"
        : > "$LOG"
        SHARED_ENV_DETACHED=1 setsid nohup bash "$0" "$@" >"$LOG" 2>&1 </dev/null &
    else
        echo "[shared-env] a build is already running: following it"
    fi
    exec 9>&- # the build holds the lock now
    tail -n +1 -F "$LOG" 2>/dev/null &
    follower=$!
    while [ ! -f "$STATUS" ]; do sleep 2; done
    sleep 1
    kill "$follower" 2>/dev/null || true
    exit "$(cat "$STATUS")"
fi
trap 'echo $? > "$STATUS"' EXIT

say() { echo "[shared-env] $*"; }

# ---- uv, the version the lock was written with --------------------------
UV=$ROOT/bin/uv
if [ ! -x "$UV" ] || [ "$("$UV" --version | cut -d' ' -f2)" != "$UV_VERSION" ]; then
    say "installing uv $UV_VERSION in $ROOT/bin"
    mkdir -p "$ROOT/bin"
    curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" \
        | env UV_UNMANAGED_INSTALL="$ROOT/bin" sh >/dev/null
fi
export UV_CACHE_DIR=$ROOT/cache
export UV_PYTHON_INSTALL_DIR=$ROOT/python
export UV_PYTHON_PREFERENCE=only-managed
export UV_LINK_MODE=hardlink
export UV_NO_CONFIG=1
# A room machine may reach the internet through a slow proxy.
export UV_HTTP_TIMEOUT=${UV_HTTP_TIMEOUT:-300}
export UV_CONCURRENT_DOWNLOADS=${UV_CONCURRENT_DOWNLOADS:-4}

# ---- the environment of this lock ---------------------------------------
HASH=$(sha256sum "$INCOMING/uv.lock" | cut -c1-16)
ENV=$ROOT/$HASH
if [ -f "$ENV/.complete" ]; then
    say "environment $HASH already built"
else
    say "building environment $HASH (Python $PYTHON)"
    rm -rf "$ENV"
    (cd "$INCOMING" && UV_PROJECT_ENVIRONMENT=$ENV \
        "$UV" sync --frozen --no-install-project --python "$PYTHON")
    cp "$INCOMING/pyproject.toml" "$INCOMING/uv.lock" "$ENV/"
    [ -f "$INCOMING/resources.py" ] && cp "$INCOMING/resources.py" "$ENV/"
    (cd "$INCOMING" && "$UV" export --frozen --no-hashes --no-header \
        --no-emit-project -o "$ENV/constraints.txt" >/dev/null)
    if [ -n "$CACHE" ]; then
        SITE=$("$ENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
        cat > "$SITE/zz_course_cache.pth" <<EOF
import os; os.environ.setdefault('CS_LAB_CACHE_PATH', '$CACHE'); os.environ.setdefault('IR_DATASETS_HOME', '$CACHE/ir_datasets')
EOF
    fi
    touch "$ENV/.complete"
fi
"$ENV/bin/python" -c 'import cs_lab' \
    || { echo "error: cs_lab does not import in $ENV" >&2; exit 1; }

# ---- the resources the notebooks load -----------------------------------
if [ -n "$CACHE" ] && [ -f "$ENV/resources.py" ]; then
    say "downloading the resources into $CACHE"
    mkdir -p "$CACHE"
    CS_LAB_CACHE_PATH=$CACHE IR_DATASETS_HOME=$CACHE/ir_datasets \
        "$ENV/bin/cs-lab" cache download --from "$ENV/resources.py" --keep-going
fi

# ---- switch, then drop the old environments -----------------------------
ln -sfn "$HASH" "$ROOT/.$LINK.tmp"
mv -T "$ROOT/.$LINK.tmp" "$ROOT/$LINK"
say "$ROOT/$LINK -> $HASH"

in_use=" $(readlink "$ROOT/current" 2>/dev/null || true) $(readlink "$ROOT/current-dev" 2>/dev/null || true) "
# Environment directories only (16 hex digits), newest first.
mapfile -t envs < <(cd "$ROOT" && ls -1dt -- [0-9a-f]*/ 2>/dev/null \
    | sed 's:/$::' | grep -E '^[0-9a-f]{16}$' || true)
kept=0
for env in "${envs[@]}"; do
    case "$in_use" in *" $env "*) continue ;; esac
    kept=$((kept + 1))
    if [ "$kept" -gt "$KEEP" ]; then
        say "removing old environment $env"
        rm -rf -- "${ROOT:?}/$env"
    fi
done
say "done: $ROOT/$LINK (python: $ROOT/$LINK/bin/python)"
