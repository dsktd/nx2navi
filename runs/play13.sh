#!/usr/bin/env sh
# purpose: fallback, the last pre-rebase build: exe play13 with the old daily settings (the retired try-vram/try-i2f/try recipes inlined)
# tracker: #177  date: 2026-11-12  owner: tally
# delete when: the rebased build (runs/play.sh) has held up for a while
# These knobs (RT_RECYCLE, STALE_LIVE, RELEASED_LRU, AO_ORDER, RT_TRIM, LIVE_IDLE) exist only on the pre-rebase `build` branch.
V="$(dirname "$0")/../NX2navi/build/v111"
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play13}" NX2NAVI_EXE="${NX2NAVI_EXE:-play13}"
export NX2NAVI_WATCH_REQ="${NX2NAVI_WATCH_REQ:-1}" NX2NAVI_SHADER_RELOAD="${NX2NAVI_SHADER_RELOAD:-1}" NX2NAVI_DUMP_REQ="${NX2NAVI_DUMP_REQ:-1}"
export NX2NAVI_TEX_RELEASED_YIELD="${NX2NAVI_TEX_RELEASED_YIELD:-85}" NX2NAVI_ALIAS_EXTRA_MIB="${NX2NAVI_ALIAS_EXTRA_MIB:-512}"
export NX2NAVI_AO_ORDER="${NX2NAVI_AO_ORDER:-1}" NX2NAVI_SHADOW_NT="${NX2NAVI_SHADOW_NT:-1}"
export NX2NAVI_TEX_RT_RECYCLE="${NX2NAVI_TEX_RT_RECYCLE:-1}" NX2NAVI_TEX_RT_TRIM="${NX2NAVI_TEX_RT_TRIM:-85}" NX2NAVI_TEX_RT_TRIM_PER_MIN="${NX2NAVI_TEX_RT_TRIM_PER_MIN:-0}"
export NX2NAVI_TEX_RELEASED_MIB="${NX2NAVI_TEX_RELEASED_MIB:-1536}" NX2NAVI_TEX_RELEASED_LRU="${NX2NAVI_TEX_RELEASED_LRU:-1}"
export NX2NAVI_TEX_LIVE_IDLE="${NX2NAVI_TEX_LIVE_IDLE:-900}" NX2NAVI_TEX_STALE_LIVE="${NX2NAVI_TEX_STALE_LIVE:-1}"
export NX2NAVI_MARK_CHORD="${NX2NAVI_MARK_CHORD:-off}" NX2NAVI_TEX_DESC_STRICT="${NX2NAVI_TEX_DESC_STRICT:-1}"
export NX2NAVI_XLATE="${NX2NAVI_XLATE:-$V/xlate-i2f/nx2navi_xlate}"
export NX2NAVI_SHADER_CACHE="${NX2NAVI_SHADER_CACHE:-$V/shader-cache-i2f}"
export NX2NAVI_PIPELINE_CACHE="${NX2NAVI_PIPELINE_CACHE:-$V/pipeline-cache-i2f.bin}"
exec just -f "$(dirname "$0")/../justfile" play-text "" "$@"
