#!/bin/bash
# NX2navi kit launcher (inside the Flatpak). First run: builds the game from the user's own .nup into the data dir;
# later runs: plays. Every step leaves a stamp in $WORK/state, so an interrupted build resumes where it stopped.
#
#   nx2navi [game.nup]          build what is missing, then play (game args after --)
#   nx2navi build [game.nup]    only build
#   nx2navi rebuild             forget the game build (keeps extracted files, profile, nx2navi.ini) and build again
#   nx2navi status              the steps and their state
set -euo pipefail

VER=v111
WORK=${XDG_DATA_HOME:-$HOME/.local/share}/nx2navi
SRC=$WORK/NX2navi
STATE=$WORK/state
OUT=$SRC/build/$VER
KIT_ID=$(cat /app/kit/id)
mkdir -p "$STATE" "$WORK/logs"
LOG=$WORK/logs/kit-$(date +%Y%m%d-%H%M%S).log

export PATH=/app/llvm/bin:$PATH
export LD_LIBRARY_PATH=/app/llvm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export NX2NAVI_VMA_INCLUDE=/app/include
export GIT_CEILING_DIRECTORIES=$WORK

say() { printf '\n== %s\n' "$*" | tee -a "$LOG"; }
die() { printf '\nnx2navi: %s\n' "$*" | tee -a "$LOG" >&2; exit 1; }
done_() { [ "$(cat "$STATE/$1" 2>/dev/null)" = "$2" ]; }
mark() { printf '%s\n' "$2" > "$STATE/$1"; }
run() { "$@" 2>&1 | tee -a "$LOG"; }

# The .nup: an argument (with `flatpak run --file-forwarding io.github.dsktd.NX2navi @@ game.nup @@` the document
# portal hands it in), else a *.nup in the data dir.
find_nup() {
    if [ -n "${1:-}" ]; then NUP=$(realpath "$1"); return; fi
    NUP=$(ls "$WORK"/*.nup 2>/dev/null | head -n1 || true)
    [ -n "$NUP" ] || die "no game dump. Put your own Ocarina of Time 1.1.1 .nup into
    $WORK/
or start it once with the file:
    flatpak run --file-forwarding io.github.dsktd.NX2navi @@ /path/to/game.nup @@
Nothing of the game is in this Flatpak; the build lands in $WORK (about 60 GB)."
}

sync_sources() {   # a new kit: copy its sources over the work tree (build/ and generated/ are not in the kit)
    done_ sources "$KIT_ID" && return
    say "1/5 copying the kit's sources into $SRC"
    mkdir -p "$SRC"
    cp -a --reflink=auto /app/src/NX2navi/. "$SRC/"
    ln -sfn /app/venv312 "$SRC/.venv"
    ln -sfn /app/venv314 "$SRC/.venv-py314"
    [ -e "$SRC/config.local.toml" ] || cp "$SRC/config.example.toml" "$SRC/config.local.toml"
    rm -f "$STATE/game" "$STATE/shaders"   # new code: lift and compile again
    mark sources "$KIT_ID"
}

extract() {
    local id; id=$(stat -c '%s-%Y' "$NUP")
    done_ extract "$id" && return
    say "2/5 extracting $NUP (exefs and romfs, about 30 GB; resumable)"
    local stub=$WORK/.msys-stub
    mkdir -p "$stub/bin" "$stub/lib" "$stub/include/vma"
    touch "$stub/bin/clang.exe" "$stub/bin/clang++.exe" "$stub/bin/SDL3.dll" "$stub/lib/libSDL3.dll.a"
    (cd "$SRC" && run .venv/bin/python -I tools/make_game.py --nup "$NUP" --out "build/extracted/$VER" --until romfs --msys "$stub")
    rm -f "$STATE/game" "$STATE/shaders"   # a game update: everything after it again
    mark extract "$id"
}

game() {
    done_ game "$KIT_ID" && [ -x "$OUT/nx2navi" ] && return
    say "3/5 lifting and compiling the game (Zen 2 and newer: AVX2; an hour or more on a Steam Deck; ninja resumes)"
    (cd "$SRC" && run python3 -I /app/kit/build-linux.py --src "$SRC" --extracted "build/extracted/$VER" --out "build/$VER" --cpu v3)
    mark game "$KIT_ID"
}

shaders() {
    done_ shaders "$KIT_ID" && return
    say "4/5 preparing shaders (opens a window; leave it open until it closes itself)"
    (cd "$SRC" && run env RADV_DEBUG=${RADV_DEBUG:-nogpl} .venv-py314/bin/python tools/prepare_shaders.py "build/$VER" \
        --romfs "build/extracted/$VER/romfs" --exefs "build/extracted/$VER/exefs" --no-list)
    mark shaders "$KIT_ID"
}

build() {
    sync_sources
    if [ -n "${1:-}" ] || [ ! -s "$STATE/extract" ]; then   # a .nup given (a game update) or never extracted
        find_nup "${1:-}"
        extract
    fi
    game
    shaders
}

play() {
    say "5/5 playing (log: $LOG)"
    cd "$SRC"
    # the justfile's play defaults, each overridable from the environment; Mesa comes from the runtime's GL extension
    export RADV_DEBUG=${RADV_DEBUG:-nogpl}
    export SDL_JOYSTICK_HIDAPI_STEAM=${SDL_JOYSTICK_HIDAPI_STEAM:-0}
    export NX2NAVI_PIPE_SKIP=${NX2NAVI_PIPE_SKIP:-any}
    export NX2NAVI_HDR=${NX2NAVI_HDR:-native}
    export NX2NAVI_REPLAY_ASYNC=${NX2NAVI_REPLAY_ASYNC:-1}
    export NX2NAVI_VK_RECORDER=${NX2NAVI_VK_RECORDER:-1}
    exec "$OUT/nx2navi" "$@" > >(tee -a "$LOG") 2>&1
}

case "${1:-}" in
    status)
        for s in sources extract game shaders; do printf '%-8s %s\n' "$s" "$(cat "$STATE/$s" 2>/dev/null || echo missing)"; done
        echo "kit $KIT_ID, data $WORK" ;;
    rebuild) rm -f "$STATE/game" "$STATE/shaders"; build "${2:-}" ;;
    build) build "${2:-}" ;;
    *)
        nup=; if [ -n "${1:-}" ] && [ "$1" != -- ]; then nup=$1; shift; fi
        [ "${1:-}" = -- ] && shift
        build "$nup"
        play "$@" ;;
esac
