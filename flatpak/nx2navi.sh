#!/bin/bash
# NX2navi kit launcher (inside the Flatpak). Without a game in the data dir it shows the setup screen (nx2navi-setup:
# fullscreen, pad-driven, works in Steam Deck Game Mode): build from the user's own .nup on this device, or import a
# game exported by this kit elsewhere. With a game it plays at once.
#
#   nx2navi [-- game args]       setup if needed, then play
#   nx2navi setup                the setup screen even with a game (rebuild, or import another)
#   nx2navi build [game.nup]     build without the screen (terminal); resumes where it stopped
#   nx2navi import <file|dir>    a .nx2navi.tar.zst (or its unpacked folder) from `nx2navi export`
#   nx2navi export [file]        pack this game for another device: no saves, logs or settings
#   nx2navi status               the steps and their state
set -euo pipefail

VER=v111
WORK=${XDG_DATA_HOME:-$HOME/.local/share}/nx2navi
SRC=$WORK/NX2navi
STATE=$WORK/state
OUT=$SRC/build/$VER
EXT=$SRC/build/extracted/$VER
KIT_ID=$(cat /app/kit/id)
# The Steam Deck has 4 cores / 8 threads and 16 GB shared with the GPU: 6 compile jobs leave room; the link is one job
JOBS=${NX2NAVI_JOBS:-6}
mkdir -p "$STATE" "$WORK/logs"
LOG=$WORK/logs/kit-$(date +%Y%m%d-%H%M%S).log
PROGRESS=$STATE/progress

export PATH=/app/llvm/bin:$PATH
export LD_LIBRARY_PATH=/app/llvm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export NX2NAVI_VMA_INCLUDE=/app/include
export GIT_CEILING_DIRECTORIES=$WORK

say() { printf '\n== %s\n' "$*" | tee -a "$LOG"; }
die() { printf '\nnx2navi: %s\n' "$*" | tee -a "$LOG" >&2; progress_set state failed; exit 1; }
done_() { [ "$(cat "$STATE/$1" 2>/dev/null)" = "$2" ]; }
mark() { printf '%s\n' "$2" > "$STATE/$1"; }
run() { "$@" >> "$LOG" 2>&1; }

# The progress file nx2navi-setup shows: step, pct, eta, msg, state
declare -A P=([step]="" [pct]=0 [eta]=-1 [msg]="" [state]=running)
progress_set() {
    P[$1]=$2
    local k; { for k in step pct eta msg state; do printf '%s %s\n' "$k" "${P[$k]}"; done; } > "$PROGRESS.tmp"
    mv "$PROGRESS.tmp" "$PROGRESS"
}
STEP_T0=0
step() {   # step <k> <name>: k of 4 overall
    say "$1/4 $2"
    STEP_T0=$(date +%s)
    progress_set step "Step $1 of 4: $2"; progress_set pct 0; progress_set eta -1; progress_set msg ""
}
# while a step runs: the log's last line as msg, and for ninja its [done/total] as pct with an ETA from the rate
watch_log() {
    while sleep 2; do
        local last; last=$(tail -c 2000 "$LOG" | tr '\r' '\n' | grep -v '^\s*$' | tail -n1 || true)
        progress_set msg "${last:0:60}"
        if [[ $last =~ ^\[([0-9]+)/([0-9]+)\] ]]; then
            local d=${BASH_REMATCH[1]} t=${BASH_REMATCH[2]} el=$(($(date +%s) - STEP_T0))
            progress_set pct $((100 * d / t))
            [ "$d" -gt 0 ] && progress_set eta $((el * (t - d) / d))
        fi
    done
}

valid_game() { [ -x "$OUT/nx2navi" ] && [ -f "$EXT/romfs/romfs.bin" ] && [ -f "$EXT/exefs/main.npdm" ]; }

sync_sources() {   # a new kit: copy its sources over the work tree (build/ is not in the kit, except build/xlate)
    done_ sources "$KIT_ID" && return
    say "copying the kit's sources into $SRC"
    mkdir -p "$SRC"
    cp -a --reflink=auto /app/src/NX2navi/. "$SRC/"
    ln -sfn /app/venv312 "$SRC/.venv"
    ln -sfn /app/venv314 "$SRC/.venv-py314"
    [ -e "$SRC/config.local.toml" ] || cp "$SRC/config.example.toml" "$SRC/config.local.toml"
    mark sources "$KIT_ID"
}

build() {   # build <nup>: the four steps, each skipped when its stamp says done
    local nup=$1 id
    [ -f "$nup" ] || die "no such file: $nup"
    id=$(stat -c '%s-%Y' "$nup")
    sync_sources
    progress_set state running
    watch_log & local watcher=$!
    trap 'kill $watcher 2>/dev/null' RETURN
    if ! done_ extract "$id"; then
        step 1 "Unpacking the game (about 30 min)"
        local stub=$WORK/.msys-stub
        mkdir -p "$stub/bin" "$stub/lib" "$stub/include/vma"
        touch "$stub/bin/clang.exe" "$stub/bin/clang++.exe" "$stub/bin/SDL3.dll" "$stub/lib/libSDL3.dll.a"
        rm -f "$STATE/game" "$STATE/shaders"
        (cd "$SRC" && run .venv/bin/python -I tools/make_game.py --nup "$nup" --out "build/extracted/$VER" --until romfs --msys "$stub") ||
            die "unpacking failed (log $LOG)"
        mark extract "$id"
    fi
    if ! done_ game "$KIT_ID" || [ ! -x "$OUT/nx2navi" ]; then
        step 2 "Translating and compiling (2 to 4 hours)"
        (cd "$SRC" && run python3 -I /app/kit/build-linux.py --src "$SRC" --extracted "build/extracted/$VER" --out "build/$VER" --cpu v3 --jobs "$JOBS") ||
            die "compiling failed (log $LOG)"
        mark game "$KIT_ID"
    fi
    if ! done_ shaders "$KIT_ID"; then
        step 3 "Preparing shaders (30 to 60 min)"
        (cd "$SRC" && run env RADV_DEBUG=${RADV_DEBUG:-nogpl} .venv-py314/bin/python tools/prepare_shaders.py "build/$VER" \
            --romfs "build/extracted/$VER/romfs" --exefs "build/extracted/$VER/exefs" --no-list) || die "shader preparation failed (log $LOG)"
        mark shaders "$KIT_ID"
    fi
    step 4 "Done"
    progress_set pct 100
    progress_set state done
}

import() {   # import <.nx2navi.tar.zst | folder>: a game from `export`, checked against this kit and this CPU
    local from=$1 tmp=$WORK/import.tmp
    rm -rf "$tmp"; mkdir -p "$tmp"
    progress_set state running
    step 1 "Importing a prebuilt game"
    if [ -d "$from" ]; then cp -a --reflink=auto "$from/." "$tmp/"
    else (cd "$tmp" && zstd -dc "$from" | tar -x) || die "cannot unpack $from"; fi
    [ -f "$tmp/NX2NAVI-EXPORT" ] || die "not an NX2navi export: $from"
    local kit cpu ver
    kit=$(sed -n 's/^kit //p' "$tmp/NX2NAVI-EXPORT"); cpu=$(sed -n 's/^cpu //p' "$tmp/NX2NAVI-EXPORT"); ver=$(sed -n 's/^ver //p' "$tmp/NX2NAVI-EXPORT")
    [ "$ver" = "$VER" ] || die "export is game version $ver, this kit plays $VER"
    [ "$kit" = "$KIT_ID" ] || die "export was built by kit $kit, this is kit $KIT_ID: update the kit on one side so both match"
    [ "$cpu" != v3 ] || grep -qw avx2 /proc/cpuinfo || die "export needs AVX2 (cpu v3); this CPU has none"
    [ -x "$tmp/build/$VER/nx2navi" ] && [ -f "$tmp/build/extracted/$VER/romfs/romfs.bin" ] || die "export is incomplete"
    sync_sources
    progress_set msg "moving files into place"
    mkdir -p "$SRC/build/extracted"
    local keep; keep=$(mktemp -d "$WORK/keep.XXXX")   # this device's saves and settings survive an import
    for k in profile nx2navi.ini logs; do [ -e "$OUT/$k" ] && mv "$OUT/$k" "$keep/"; done
    rm -rf "$OUT" "$EXT"
    mv "$tmp/build/$VER" "$OUT"; mv "$tmp/build/extracted/$VER" "$EXT"
    for k in profile nx2navi.ini logs; do [ -e "$keep/$k" ] && mv "$keep/$k" "$OUT/"; done
    rm -rf "$tmp" "$keep"
    mark extract imported; mark game "$KIT_ID"; mark shaders "$KIT_ID"
    progress_set pct 100; progress_set state done
}

export_game() {   # export [file]: the game folder without saves, logs, settings, objects or debug dumps
    valid_game || { echo "nx2navi: no built game in $WORK" >&2; exit 1; }
    local to=${1:-$WORK/game-$VER.nx2navi.tar.zst}
    printf 'kit %s\ncpu v3\nver %s\n' "$KIT_ID" "$VER" > "$SRC/NX2NAVI-EXPORT"
    echo "packing $to (about 30 GB, several minutes)"
    (cd "$SRC" && tar -c --exclude="build/$VER/profile" --exclude="build/$VER/logs" --exclude="build/$VER/nx2navi.ini*" \
        --exclude="build/$VER/obj" --exclude="build/$VER/gen" --exclude="build/$VER/dump*" --exclude="build/$VER/reload-bak" \
        --exclude="build/$VER/mesa-cache" --exclude="build/$VER/pipeline-cache.bin" --exclude='*.map' --exclude='*.rsp' --exclude="build/extracted/$VER/build-cache" \
        NX2NAVI-EXPORT "build/$VER" "build/extracted/$VER" | zstd -T0 -3 -q -o "$to")
    rm -f "$SRC/NX2NAVI-EXPORT"
    echo "done: $to. For your own devices only. Copy it to the other device and pick it under Import."
}

# The setup screen: pick a source, then the progress screen while the build or import runs. Without a display
# (or when the screen fails) it falls back to the terminal.
setup() {
    local choice
    choice=$(nx2navi-setup pick "$WORK") || exit 0
    case $choice in
        "nup "*) build "${choice#nup }" & ;;
        "import "*) import "${choice#import }" & ;;
        *) exit 0 ;;
    esac
    local job=$!
    nx2navi-setup progress "$PROGRESS" || true
    wait $job || exit 1
}

play() {
    cd "$SRC"
    # the paths the binary baked in point to the machine it was built on (an import): name them
    export NX2NAVI_EXEFS=$EXT/exefs NX2NAVI_ROMFS=$EXT/romfs NX2NAVI_PROFILE_DIR=${NX2NAVI_PROFILE_DIR:-$OUT/profile}
    # the justfile's play defaults, each overridable from the environment; Mesa comes from the runtime's GL extension
    export RADV_DEBUG=${RADV_DEBUG:-nogpl}
    export SDL_JOYSTICK_HIDAPI_STEAM=${SDL_JOYSTICK_HIDAPI_STEAM:-0}
    export NX2NAVI_PIPE_SKIP=${NX2NAVI_PIPE_SKIP:-any}
    export NX2NAVI_HDR=${NX2NAVI_HDR:-native}
    export NX2NAVI_REPLAY_ASYNC=${NX2NAVI_REPLAY_ASYNC:-0}
    export NX2NAVI_VK_RECORDER=${NX2NAVI_VK_RECORDER:-1}
    exec "$OUT/nx2navi" "$@" > >(tee -a "$WORK/logs/play-$(date +%Y%m%d-%H%M%S).log") 2>&1
}

case "${1:-}" in
    status)
        for s in sources extract game shaders; do printf '%-8s %s\n' "$s" "$(cat "$STATE/$s" 2>/dev/null || echo missing)"; done
        echo "kit $KIT_ID, data $WORK"; cat "$PROGRESS" 2>/dev/null || true ;;
    build)
        echo "log: $LOG"; touch "$LOG"
        build "${2:-$(ls "$WORK"/*.nup 2>/dev/null | head -n1)}" & job=$!
        tail -f --pid=$job "$LOG"; wait $job ;;
    import) import "$2" ;;
    export) export_game "${2:-}" ;;
    setup) setup; valid_game && play ;;
    *)
        [ "${1:-}" = -- ] && shift
        if ! valid_game || ! done_ game "$KIT_ID" || ! done_ shaders "$KIT_ID"; then setup; fi
        valid_game || exit 0
        play "$@" ;;
esac
