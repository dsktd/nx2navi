#!/usr/bin/env sh
# purpose: play44's stack rebased onto upstream 0.9.2 (a32597b, branch rebase4); play44's knobs (clock.sh) without
# the raw memory snapshot: replay in step, per-frame trace, mark ring; translator unchanged (xlate-play33)
# tracker: #132  date: 2026-11-12  owner: tally   (A/B against play44: same knobs, NX2NAVI_EXE=play44)
# delete when: a later rebase replaces it
export NX2NAVI_RUN_NAME="${NX2NAVI_RUN_NAME:-play46}" NX2NAVI_EXE="${NX2NAVI_EXE:-play46}"
# 0.9.2's default too (0533b30); kept explicit until play45's async sync fix is in
export NX2NAVI_REPLAY_ASYNC="${NX2NAVI_REPLAY_ASYNC:-0}"
export NX2NAVI_TRACE="${NX2NAVI_TRACE:-perf}" NX2NAVI_MARK_RING="${NX2NAVI_MARK_RING:-120}" NX2NAVI_MARK_BURST="${NX2NAVI_MARK_BURST:-120}"
exec sh "$(dirname "$0")/play43.sh" "$@"
