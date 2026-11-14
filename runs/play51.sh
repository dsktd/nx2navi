#!/usr/bin/env sh
# purpose: the `build` branch at d2d2e64 (= deck4: our stack + 0120 merged onto upstream v0.10.1 5ae55db); desktop and
#   Deck share this commit. Knobs as play50 (async replay + gate + hold); upstream's new defaults kept
#   (NX2NAVI_REPLAY_WORKERS=auto, NX2NAVI_TAIL_EARLY=1, PIPE_RELEASE, SHADER_COMPRESS, TEX_RELEASED_HOLD).
# tracker: #123  date: 2026-11-14  owner: tally   (A/B: NX2NAVI_REPLAY_WORKERS=0 NX2NAVI_TAIL_EARLY=0 = play50's)
# delete when: a later build replaces it
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play51}" NX2NAVI_EXE="${NX2NAVI_EXE:-play51}"
exec sh "$(dirname "$0")/skysh.sh" "$@"
