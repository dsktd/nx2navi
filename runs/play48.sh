#!/usr/bin/env sh
# purpose: play47 (play46 + 0109 async gate) + 0112 NX2NAVI_FFX_LIB (FSR 3.1 library on Linux; framegen stays off)
# tracker: #132  date: 2026-11-12  owner: tally   (A/B: NX2NAVI_REPLAY_ASYNC=0 or NX2NAVI_ASYNC_GATE=0 on the same exe)
# delete when: a later rebase replaces it
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play48}" NX2NAVI_EXE="${NX2NAVI_EXE:-play48}"
export NX2NAVI_REPLAY_ASYNC="${NX2NAVI_REPLAY_ASYNC:-1}" NX2NAVI_ASYNC_GATE="${NX2NAVI_ASYNC_GATE:-1}"
exec sh "$(dirname "$0")/play46.sh" "$@"
