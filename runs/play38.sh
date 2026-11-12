#!/usr/bin/env sh
# purpose: scene-entry fix plus the shadow-list lock: exe play38 (rebase-upstream 977acc7 + 0100 74266d8 on branch play38), patches 0099 + 0101 + 0100 on
# tracker: #132  date: 2026-11-12  owner: tally   (A/B: NX2NAVI_SHADOW_TOUCH_LOCK=0 sh runs/play38.sh)
# delete when: the knobs are the defaults of runs/play.sh, or Cal rejects them
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play38}" NX2NAVI_EXE="${NX2NAVI_EXE:-play38}"
export NX2NAVI_SHADOW_PRESYNC="${NX2NAVI_SHADOW_PRESYNC:-1}" NX2NAVI_POOL_IDLE_MS="${NX2NAVI_POOL_IDLE_MS:-8}"
export NX2NAVI_SHADOW_TOUCH_LOCK="${NX2NAVI_SHADOW_TOUCH_LOCK:-1}"
exec sh "$(dirname "$0")/play.sh" "$@"
