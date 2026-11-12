#!/usr/bin/env sh
# purpose: play44 + 0109 NX2NAVI_ASYNC_GATE: async replay again, with its submit call waiting for the game's CPU
# signal before the uniform snapshot (the two-frame-old world / judder fix)
# tracker: #132  date: 2026-11-12  owner: tally   (A/B: NX2NAVI_ASYNC_GATE=0 on the same exe)
# delete when: a later rebase replaces it, or the knobs are the defaults of runs/play.sh
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play45}" NX2NAVI_EXE="${NX2NAVI_EXE:-play45}"
export NX2NAVI_REPLAY_ASYNC="${NX2NAVI_REPLAY_ASYNC:-1}" NX2NAVI_ASYNC_GATE="${NX2NAVI_ASYNC_GATE:-1}"
exec sh "$(dirname "$0")/play44.sh" "$@"
