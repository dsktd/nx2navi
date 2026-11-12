#!/usr/bin/env sh
# purpose: upstream bump: exe play41 (branch rebase3 = play38's stack rebased onto origin/main 322d7c0, 0.9.1+), play38's knobs
# tracker: #132  date: 2026-11-12  owner: tally   (A/B against play38: same knobs, NX2NAVI_EXE=play38)
# delete when: a later rebase replaces it, or the knobs are the defaults of runs/play.sh
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play41}" NX2NAVI_EXE="${NX2NAVI_EXE:-play41}"
export NX2NAVI_SHADOW_PRESYNC="${NX2NAVI_SHADOW_PRESYNC:-1}" NX2NAVI_POOL_IDLE_MS="${NX2NAVI_POOL_IDLE_MS:-8}"
export NX2NAVI_SHADOW_TOUCH_LOCK="${NX2NAVI_SHADOW_TOUCH_LOCK:-1}"
# translator: rebase3 has the same tools/xlate inputs as rebase2 (0.9.0 + upstream 0041 CAS + our 0041 clamp): xlate-play33
export NX2NAVI_XLATE="${NX2NAVI_XLATE:-$HOME/claude/nx2navi/NX2navi/build/v111/xlate-play33/nx2navi_xlate}"
exec sh "$(dirname "$0")/play.sh" "$@"
