#!/usr/bin/env sh
# purpose: play41 + patch 0106 (mark recipes: every mark/shot.req writes logs/mark-<present>.dbg; NX2NAVI_MARK_RECIPE default 1)
# tracker: #132  date: 2026-11-12  owner: tally   (A/B against play41: same knobs, NX2NAVI_EXE=play41)
# delete when: a later rebase replaces it, or the knobs are the defaults of runs/play.sh
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play42}" NX2NAVI_EXE="${NX2NAVI_EXE:-play42}"
export NX2NAVI_MARK_RECIPE="${NX2NAVI_MARK_RECIPE:-1}"
exec sh "$(dirname "$0")/play41.sh" "$@"
