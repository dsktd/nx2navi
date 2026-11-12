#!/usr/bin/env sh
# purpose: find the time-of-day value with Cal: exe `play44` (play43 + 0108 memory search commands), every mark also writes a raw
# memory snapshot (NX2NAVI_MARK_RECIPE=2). Cal marks (F9) before and after playing the Sun's Song; a lab agent diffs.
# tracker: recipes / clock  date: 2026-11-12  owner: tally  delete when: the clock key is in the recipe format
export NX2NAVI_RUN_NAME=clock NX2NAVI_MARK_RECIPE=2 NX2NAVI_EXE=play44
exec sh "$(dirname "$0")/play43.sh" "$@"
