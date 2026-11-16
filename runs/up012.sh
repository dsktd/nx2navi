#!/bin/sh
# tracker: #179  date: 2026-11-15  owner: tally   CANDIDATE (Cal judges defaults; UNCERTAIN.md)
# exe up012 (build up012 tip = old build c4b2254 merged onto upstream 0.12.0 62cc3b1; 0126/0128/0129 dropped for
# upstream's own commits), on top of runs/xl701.sh (translator 701e7ce, pool 40960; upstream always refuses
# 32768-pool carried translations, SHADER_CARRY_POOL is unused now).
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-up012}" NX2NAVI_EXE="${NX2NAVI_EXE:-up012}"
exec sh "$(dirname "$0")/xl701.sh" "$@"
