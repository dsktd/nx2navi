#!/usr/bin/env sh
# purpose: the last pre-rebase setup: play13 with TEX_DESC_STRICT plus try-vram's memory settings and the text mod
# tracker: fallback while the rebase (play22+) is tested; #177  date: 2026-11-11  owner: tally
# delete when: the rebased build is the default and holds up
export NX2NAVI_RUN_NAME=play13 NX2NAVI_EXE=play13 NX2NAVI_TEX_DESC_STRICT=1
exec just -f "$(dirname "$0")/../justfile" try-name "" "$@"
