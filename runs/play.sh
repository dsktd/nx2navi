#!/usr/bin/env sh
# purpose: the usual play setup: the build rebased onto upstream (worktree .lab/wt-rebase, patches through 0096), exe play32
# tracker: #177  date: 2026-11-12  owner: tally   (other exe: NX2NAVI_EXE=play33 just run; any NX2NAVI_ knob overrides)
# delete when: never; edit the exe name when a newer build is the best one
V="$(dirname "$0")/../NX2navi/build/v111"
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play}"   # the log's build line names it
export NX2NAVI_EXE="${NX2NAVI_EXE:-play32}"
# live debugging requests (shot/dump/watch/pick .req, F5/F6/F12 keys, shader reload); L3+R3 stays with the game
export NX2NAVI_WATCH_REQ="${NX2NAVI_WATCH_REQ:-1}" NX2NAVI_SHADER_RELOAD="${NX2NAVI_SHADER_RELOAD:-1}" NX2NAVI_DUMP_REQ="${NX2NAVI_DUMP_REQ:-1}"
export NX2NAVI_MARK_CHORD="${NX2NAVI_MARK_CHORD:-off}"
export NX2NAVI_ALIAS_EXTRA_MIB="${NX2NAVI_ALIAS_EXTRA_MIB:-512}"
export NX2NAVI_STALL_MS="${NX2NAVI_STALL_MS:-100}" NX2NAVI_SHADOW_BULK_WRITE="${NX2NAVI_SHADOW_BULK_WRITE:-1}"
export NX2NAVI_TEX_DESC_STRICT="${NX2NAVI_TEX_DESC_STRICT:-1}" NX2NAVI_TEX_RELEASED_MB="${NX2NAVI_TEX_RELEASED_MB:-3072}"
export NX2NAVI_XLATE="${NX2NAVI_XLATE:-$V/xlate-rebase/nx2navi_xlate}"
export NX2NAVI_SHADER_CACHE="${NX2NAVI_SHADER_CACHE:-$V/shader-cache-rebase}"
export NX2NAVI_PIPELINE_CACHE="${NX2NAVI_PIPELINE_CACHE:-$V/pipeline-cache-rebase.bin}"
exec just -f "$(dirname "$0")/../justfile" play-text "" "$@"
