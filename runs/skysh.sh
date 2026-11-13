#!/usr/bin/env sh
# purpose: play49 + 0114 NX2NAVI_ASYNC_HOLD (the sky-SH block's CPU writes reach the VRAM mirror in submission order
#   under async replay: actors keep their sky light at night; SYMPTOMS "Actors ... black at night")
# tracker: #150  date: 2026-11-12  owner: tally   (A/B: NX2NAVI_ASYNC_HOLD= on the same exe = play49 behaviour)
# delete when: a later rebase carries 0114
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-skysh}" NX2NAVI_EXE="${NX2NAVI_EXE:-skysh}"
export NX2NAVI_ASYNC_HOLD="${NX2NAVI_ASYNC_HOLD-25a4c7f00:100}"
exec sh "$(dirname "$0")/play49.sh" "$@"
