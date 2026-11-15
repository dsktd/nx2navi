#!/bin/sh
# tracker: #149  date: 2026-11-15  owner: tally   CANDIDATE (Cal judges defaults; UNCERTAIN.md)
# exe xl149 (build 9b69085 = 0c4f210 + 0126) with the translator built from 701e7ce (texture pool 40960, upstream
# 2388f1f) instead of xlate-play33 (pool 32768: slots >= 32768 sample slot 32767). NX2NAVI_SHADER_CARRY_POOL=1 (0126,
# upstream 46c764a) stops the shader cache serving the old translator's 32768-pool translations: without it a switch
# keeps them. First start translates those shaders again (~300 in a field/graveyard session).
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-xl701}" NX2NAVI_EXE="${NX2NAVI_EXE:-xl149}"
export NX2NAVI_SHADER_CARRY_POOL="${NX2NAVI_SHADER_CARRY_POOL:-1}"
export NX2NAVI_XLATE="${NX2NAVI_XLATE:-$(dirname "$0")/../NX2navi/build/xlate-701e7ce/nx2navi_xlate}"
exec sh "$(dirname "$0")/play51.sh" "$@"
