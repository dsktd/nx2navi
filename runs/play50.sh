#!/usr/bin/env sh
# purpose: rebase5 = play49 stack + 0114 ASYNC_HOLD + 0115 tex counters + 0116 state sync + 0118 SSBO_SNAPSHOT (off)
#   onto upstream origin/main a01910d (v0.9.2-12: tail_early, replay_small, Steam co-op); knobs as skysh/play49:
#   async replay + gate + hold. Upstream's NX2NAVI_REPLAY_WORKERS / NX2NAVI_TAIL_EARLY / NX2NAVI_REPLAY_SMALL stay off.
# tracker: #132  date: 2026-11-13  owner: tally   (A/B: NX2NAVI_REPLAY_WORKERS=0..4, NX2NAVI_TAIL_EARLY=0|1 on the same exe)
# delete when: a later rebase replaces it
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play50}" NX2NAVI_EXE="${NX2NAVI_EXE:-play50}"
exec sh "$(dirname "$0")/skysh.sh" "$@"
