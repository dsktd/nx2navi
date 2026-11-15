#!/bin/sh
# tracker: #149  date: 2026-11-15  owner: tally
# play51 with the translator built from build 701e7ce (texture pool 40960, upstream 2388f1f), not xlate-rebase (Nov 11,
# clamps pool handles to slot 32767: terrain textures registered from 32768 up draw with slot 32767's image).
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-xl701}"
export NX2NAVI_XLATE="$(dirname "$0")/../NX2navi/build/xlate-701e7ce/nx2navi_xlate"
exec sh "$(dirname "$0")/play51.sh" "$@"
