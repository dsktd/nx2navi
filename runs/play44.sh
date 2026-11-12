#!/usr/bin/env sh
# purpose: play43 + 0108 (memory search commands); marks also save a raw memory snapshot (MARK_RECIPE=2) for the
# Sun's Song clock search
# tracker: #132  date: 2026-11-12  owner: tally   (A/B against play43: same knobs, NX2NAVI_EXE=play43)
# delete when: a later rebase replaces it, or the knobs are the defaults of runs/play.sh
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play44}" NX2NAVI_EXE="${NX2NAVI_EXE:-play44}"
export NX2NAVI_MARK_RECIPE="${NX2NAVI_MARK_RECIPE:-2}"
exec sh "$(dirname "$0")/play43.sh" "$@"
