#!/usr/bin/env sh
# purpose: play46 (play44 stack on upstream 0.9.2) + 0109 NX2NAVI_ASYNC_GATE (patch 0111): async replay with its
# submit call waiting for the game's CPU signal, so the replay overlaps the game frame without the two-frame-old world
# tracker: #132  date: 2026-11-12  owner: tally   (A/B: NX2NAVI_REPLAY_ASYNC=0 or NX2NAVI_ASYNC_GATE=0 on the same exe)
# delete when: a later rebase replaces it
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play47}" NX2NAVI_EXE="${NX2NAVI_EXE:-play47}"
export NX2NAVI_REPLAY_ASYNC="${NX2NAVI_REPLAY_ASYNC:-1}" NX2NAVI_ASYNC_GATE="${NX2NAVI_ASYNC_GATE:-1}"
exec sh "$(dirname "$0")/play46.sh" "$@"
