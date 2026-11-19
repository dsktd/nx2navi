#!/bin/sh
# tracker: #128  date: 2026-11-15  owner: tally   CANDIDATE (Cal judges defaults; UNCERTAIN.md)
# exe carry1 (build c4b2254 = ca12e5e + 0128 upstream 5f9374e orecord/OCARINA_TIMING=1 + 0129 upstream 5c9e480 shake
# key by updates), on top of runs/xl701.sh (translator 701e7ce + SHADER_CARRY_POOL=1).
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-carry1}" NX2NAVI_EXE="${NX2NAVI_EXE:-carry1}"
export NX2NAVI_REPLAY_ASYNC="${NX2NAVI_REPLAY_ASYNC:-0}"   # Cal 2026-11-18: async replay flickers
exec sh "$(dirname "$0")/xl701.sh" "$@"
