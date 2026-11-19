#!/bin/sh
# NX2navi on the Steam Deck: exe deck2 (deckres = play50 15d14ce + 0120) with the play50 knobs. Any NX2NAVI_ value set outside wins.
# Log: ~/nx2navi/build/v111/logs/play-<time>.log. Saves: build/v111/profile. Settings: build/v111/nx2navi.ini.
N=$HOME/nx2navi; B=$N/build/v111; cd "$B" || exit 1; mkdir -p logs
# Started by Steam (the "NX2navi" entry), not by a lab cell: the build picker (pick.py) first
if [ -n "$SteamGameId$SteamAppId" ] && [ ! -f "$N/cell.env" ] && [ -z "$NX2NAVI_PICKED" ]; then
  # NX2NAVI_PICK=<key> skips the window (tests); NX2NAVI_PICK_DRY=1 prints the final command instead of running it
  c=${NX2NAVI_PICK:-$(env -u LD_PRELOAD -u LD_LIBRARY_PATH python3 -I "$N/pick.py")} || exit 0
  export NX2NAVI_PICKED=$c
  case $c in
    stutter) export NX2NAVI_STUTTER_MAP=1 ;;
    deck5) export NX2NAVI_PLAY_ENV=$N/play.env.deck5 ;;
    upstream) ${NX2NAVI_PICK_DRY:+echo} exec "$N/upstream/play-upstream.sh" "$@"; exit ;;
  esac
fi
# Steam's own runtime libraries and overlay preload do not fit the game's glibc
unset LD_PRELOAD LD_LIBRARY_PATH
# one game at a time: two at once locked the Deck up (2026-11-13)
exec 9>"$N/.game.lock"; flock -n 9 || { echo "NX2navi is already running" >&2; exit 3; }
# a measurement cell (cell.sh) hands its settings over in cell.env and takes the log
LOG="logs/play-$(date +%Y%m%d-%H%M%S).log"
# play.env (kept; KEY=VALUE lines, no user-facing settings): which exe the entry runs. Delete the file for deck2 again
# NX2NAVI_PLAY_ENV names another such file (the picker's fallback: play.env.deck5)
PE="${NX2NAVI_PLAY_ENV:-$N/play.env}"
if [ -f "$PE" ]; then set -a; . "$PE"; set +a; fi
if [ -f "$N/cell.env" ]; then set -a; . "$N/cell.env"; set +a; rm -f "$N/cell.env"; LOG=$CELL_LOG; fi
export RADV_DEBUG="${RADV_DEBUG-nogpl}" NX2NAVI_PIPE_SKIP="${NX2NAVI_PIPE_SKIP:-strict}"
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-deck-play50}"
export NX2NAVI_EXEFS=$N/build/extracted/v111/exefs NX2NAVI_ROMFS=$N/build/extracted/v111/romfs
export NX2NAVI_XLATE=$B/xlate-play33/nx2navi_xlate NX2NAVI_SHADER_CACHE=$B/shader-cache-rebase
export NX2NAVI_PIPELINE_CACHE="${NX2NAVI_PIPELINE_CACHE:-$B/pipeline-cache-deck.bin}"
export NX2NAVI_ALIAS_EXTRA_MIB="${NX2NAVI_ALIAS_EXTRA_MIB:-512}" NX2NAVI_GPU_WAIT="${NX2NAVI_GPU_WAIT:-0}" NX2NAVI_POOL_IDLE_MS="${NX2NAVI_POOL_IDLE_MS:-8}" NX2NAVI_SHADOW_BULK_WRITE="${NX2NAVI_SHADOW_BULK_WRITE:-1}"
export NX2NAVI_SHADOW_PRESYNC="${NX2NAVI_SHADOW_PRESYNC:-1}" NX2NAVI_SHADOW_TOUCH_LOCK="${NX2NAVI_SHADOW_TOUCH_LOCK:-1}" NX2NAVI_STALL_MS="${NX2NAVI_STALL_MS:-100}" NX2NAVI_TEX_DESC_STRICT="${NX2NAVI_TEX_DESC_STRICT:-1}"
export NX2NAVI_REPLAY_ASYNC="${NX2NAVI_REPLAY_ASYNC:-0}" NX2NAVI_ASYNC_GATE="${NX2NAVI_ASYNC_GATE:-1}" NX2NAVI_ASYNC_HOLD="${NX2NAVI_ASYNC_HOLD:-25a4c7f00:100}"
# Deck memory (SYSTEM-CHANGES.md): 8 MiB dma-buf spans. Picture size, HDR, texture detail, frame limit: nx2navi.ini / the menu
export NX2NAVI_DMABUF_MB="${NX2NAVI_DMABUF_MB:-8}"
export NX2NAVI_VK_RECORDER="${NX2NAVI_VK_RECORDER:-1}" NX2NAVI_MARK_CHORD="${NX2NAVI_MARK_CHORD:-off}" NX2NAVI_TRACE="${NX2NAVI_TRACE:-perf,present}"
[ -n "$NX2NAVI_PICK_DRY" ] && { echo "exe=nx2navi.${NX2NAVI_EXE:-deck2} cache=$NX2NAVI_PIPELINE_CACHE run=$NX2NAVI_RUN_NAME stutter=${NX2NAVI_STUTTER_MAP:-0}"; exit 0; }
exec /nix/store/ynczmb6i3kjia50k0hv19biblhjdnly9-nixVulkanIntel/bin/nixVulkanIntel $N/libs.sh ./nx2navi.${NX2NAVI_EXE:-deck2} "$@" > "$LOG" 2>&1
