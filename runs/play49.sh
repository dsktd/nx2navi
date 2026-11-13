#!/usr/bin/env sh
# purpose: play48 + upstream PR #730 (guest memory as udmabuf dma-bufs instead of shadow copies); needs /dev/udmabuf rw
# tracker: #132  date: 2026-11-12  owner: tally   (A/B: NX2NAVI_DMABUF=0 on the same exe = shadow copies)
# delete when: a later rebase carries #730
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play49}" NX2NAVI_EXE="${NX2NAVI_EXE:-play49}"
exec sh "$(dirname "$0")/play48.sh" "$@"
