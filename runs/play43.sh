#!/usr/bin/env sh
# purpose: play42 + 0107 (recipes restore facing; dump.req recipe)
# tracker: #132  date: 2026-11-12  owner: tally   (A/B against play42: same knobs, NX2NAVI_EXE=play42)
# delete when: a later rebase replaces it, or the knobs are the defaults of runs/play.sh
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play43}" NX2NAVI_EXE="${NX2NAVI_EXE:-play43}"
export NX2NAVI_MARK_RECIPE="${NX2NAVI_MARK_RECIPE:-1}"
exec sh "$(dirname "$0")/play42.sh" "$@"
