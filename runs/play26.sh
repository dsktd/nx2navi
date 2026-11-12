#!/usr/bin/env sh
# purpose: play25 + 0090 NX2NAVI_EVO_ASYNC (AO reruns after its event under the async replay; play24 lighting flicker)
# tracker: #177 (consolidation follows once this holds up)  date: 2026-11-11  owner: tally (A/B: NX2NAVI_EVO_ASYNC=0)
# delete when: play22 (or its successor) becomes the default play setup
V="$(dirname "$0")/../NX2navi/build/v111"
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-$(basename "$0" .sh)}"   # the log's build line names it
export NX2NAVI_EXE=play26 NX2NAVI_STALL_MS=100 NX2NAVI_SHADOW_BULK_WRITE=1 NX2NAVI_TEX_DESC_STRICT=1 NX2NAVI_TEX_RELEASED_MB=3072
export NX2NAVI_XLATE="$V/xlate-rebase/nx2navi_xlate"
export NX2NAVI_SHADER_CACHE="$V/shader-cache-rebase"
export NX2NAVI_PIPELINE_CACHE="$V/pipeline-cache-rebase.bin"
exec just -f "$(dirname "$0")/../justfile" try-name "" "$@"
