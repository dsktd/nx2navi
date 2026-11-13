#!/usr/bin/env sh
# purpose: skysh (0114 ASYNC_HOLD) + 0118 NX2NAVI_SSBO_SNAPSHOT (bound storage buffers copied at the submit call under
#   async replay, like the uniform snapshot: the Zora flicker of 2026-11-12 that REPLAY_ASYNC=0 fixed)
# tracker: #150  date: 2026-11-12  owner: tally   (A/B: NX2NAVI_SSBO_SNAPSHOT=0 on the same exe = skysh behaviour)
# delete when: a later rebase carries 0118
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-ssnap}" NX2NAVI_EXE="${NX2NAVI_EXE:-ssnap}"
export NX2NAVI_SSBO_SNAPSHOT="${NX2NAVI_SSBO_SNAPSHOT:-1}"
exec sh "$(dirname "$0")/skysh.sh" "$@"
