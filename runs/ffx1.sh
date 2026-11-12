#!/usr/bin/env sh
# purpose: play46 + 0112 (FSR 3.1 upscaler on Linux through a locally built FidelityFX 1.1.4 port, dlopen)
# tracker: #147  date: 2026-11-12  owner: tally   (FSR is set in nx2navi.ini: upscaler = fsr, taa = fsr3)
# delete when: the upscaler is verified and folded into the main stack, or dropped
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-ffx1}" NX2NAVI_EXE="${NX2NAVI_EXE:-ffx1}" NX2NAVI_FFX_DEBUG="${NX2NAVI_FFX_DEBUG:-1}"
exec sh "$(dirname "$0")/play46.sh" "$@"
