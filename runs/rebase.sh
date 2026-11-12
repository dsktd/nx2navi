#!/usr/bin/env sh
# purpose: first sessions on the build rebased onto upstream adce9a9 (play22, 48 of our patches)
# tracker: #177 (consolidation follows once this holds up)  date: 2026-11-11  owner: tally
# delete when: play22 (or its successor) becomes the default play setup
V="$(dirname "$0")/../NX2navi/build/v111"
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-$(basename "$0" .sh)}"   # the log's build line names it
export NX2NAVI_EXE=play22 NX2NAVI_SHADOW_BULK_WRITE=1 NX2NAVI_TEX_DESC_STRICT=1 NX2NAVI_TEX_RELEASED_MB=3072
export NX2NAVI_XLATE="$V/xlate-rebase/nx2navi_xlate"
export NX2NAVI_SHADER_CACHE="$V/shader-cache-rebase"
export NX2NAVI_PIPELINE_CACHE="$V/pipeline-cache-rebase.bin"
exec just -f "$(dirname "$0")/../justfile" try-name "" "$@"
