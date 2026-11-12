#!/usr/bin/env sh
# purpose: try the scene-entry fix: exe play36 (rebase-upstream 977acc7, patches 0099 + 0101) with both knobs on
# tracker: #132  date: 2026-11-12  owner: tally   (A/B: NX2NAVI_SHADOW_PRESYNC=0 NX2NAVI_POOL_IDLE_MS=0 sh runs/play36.sh)
# delete when: the knobs are the defaults of runs/play.sh, or Cal rejects the fix
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play36}" NX2NAVI_EXE="${NX2NAVI_EXE:-play36}"
export NX2NAVI_SHADOW_PRESYNC="${NX2NAVI_SHADOW_PRESYNC:-1}" NX2NAVI_POOL_IDLE_MS="${NX2NAVI_POOL_IDLE_MS:-8}"
exec sh "$(dirname "$0")/play.sh" "$@"
