#!/usr/bin/env sh
# purpose: skysh + 0115 (texture made-origin counters, NX2NAVI_TRACE=perf lines only; same behaviour as skysh):
#   tells whether the textures made while turning the camera are released entries dropped past the size cap coming back
# tracker: #132  date: 2026-11-12  owner: tally   (SYMPTOMS "Turning the camera in a Hyrule Field grotto ...")
# delete when: the grotto question is answered (tools/pan-cell results) or a later rebase carries 0115
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-texchurn}" NX2NAVI_EXE="${NX2NAVI_EXE:-texchurn}"
exec sh "$(dirname "$0")/skysh.sh" "$@"
