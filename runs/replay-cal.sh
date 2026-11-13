#!/usr/bin/env bash
# purpose: replay Cal's input-20261112-222948 through his normal play path (his display, nx2navi.ini, Niri) with the knobs
#   of that session on exe texchurn: the host-side test of why his play runs ~64 fps and the same replay in the lab 88
#   (ARCHITECTURE.md 11 "Cal's real play vs lab replays"). Run on the host: sh runs/replay-cal.sh [sdr]
#   sdr = same run with hdr = off in nx2navi.ini for this run only (the ini is backed up and put back on exit, no env lock).
# tracker: #132  date: 2026-11-13  owner: tally
# delete when: the host-side difference is explained
# Saves: the session's start bundle copied into a scratch NX2NAVI_PROFILE_DIR, so the live saves stay untouched. Shader and
# pipeline caches are the live ones, as in his play. Ends itself at present 13600 (about 3 min), then prints the summary.
set -u
R=$(cd "$(dirname "$0")/.." && pwd); B=$R/NX2navi/build/v111; L=$B/logs; ts=20261112-222948
mode=${1:-hdr}; exe=${NX2NAVI_EXE:-texchurn}; frame=${FRAME:-13600}
log=$L/replay-cal-$mode-$(date +%H%M%S).log
last=$(ls -t $L/play-*.log | head -1)
[ $(( $(date +%s) - $(stat -c %Y $last) )) -lt 120 ] && { echo "a game is writing $last: stop it first"; exit 1; }
[ -f $L/input-$ts.txt ] && [ -d $L/profile-$ts ] || { echo "recording or save bundle missing"; exit 1; }
prof=$(mktemp -d /tmp/replay-cal-profile.XXXXXX)
cp -a $B/profile/. $prof/ && rm -rf $prof/save $prof/save-tx $prof/save-backup && cp -a $L/profile-$ts/. $prof/ || exit 1
if [ "$mode" = sdr ]; then
  cp -a $B/nx2navi.ini $B/nx2navi.ini.replay-bak || exit 1
  sed -i 's/^hdr *=.*/hdr = off/' $B/nx2navi.ini
fi
restore() { [ -f $B/nx2navi.ini.replay-bak ] && mv -f $B/nx2navi.ini.replay-bak $B/nx2navi.ini; rm -rf "$prof"; }
trap restore EXIT
xl=$(awk -F'\t' -v e=$exe '$1 == e { split($4, a, "/"); print a[1] }' $R/builds.tsv)
echo "replay-cal: mode $mode exe $exe frame $frame log $log"
cd $R/NX2navi && NX2NAVI_NVIDIA=0 setsid nix develop $R --command env TERM=dumb SDL_VIDEODRIVER=wayland SDL_JOYSTICK_HIDAPI_STEAM=0 \
  RADV_DEBUG=nogpl NX2NAVI_INPUT_SCRIPT=$L/input-$ts.txt NX2NAVI_PROFILE_DIR=$prof \
  NX2NAVI_ALIAS_EXTRA_MIB=512 NX2NAVI_ASYNC_GATE=1 NX2NAVI_ASYNC_HOLD=25a4c7f00:100 NX2NAVI_GPU_WAIT=0 \
  NX2NAVI_MARK_CHORD=off NX2NAVI_NVIDIA=0 NX2NAVI_PIPE_SKIP=any NX2NAVI_POOL_IDLE_MS=8 NX2NAVI_REPLAY_ASYNC=1 \
  NX2NAVI_SHADOW_BULK_WRITE=1 NX2NAVI_SHADOW_PRESYNC=1 NX2NAVI_SHADOW_TOUCH_LOCK=1 NX2NAVI_STALL_MS=100 \
  NX2NAVI_TEX_DESC_STRICT=1 NX2NAVI_TEX_RELEASED_MB=3072 NX2NAVI_TEX_RELEASED_MIB=3072 NX2NAVI_VK_RECORDER=1 \
  NX2NAVI_TRACE=perf,present NX2NAVI_SHADER_RELOAD=1 NX2NAVI_DUMP_REQ=1 NX2NAVI_WATCH_REQ=1 NX2NAVI_MARK_BURST=120 \
  NX2NAVI_MARK_RING=120 NX2NAVI_MARK_RECIPE=1 NX2NAVI_RUN_NAME=$exe NX2NAVI_EXE=$exe \
  NX2NAVI_PIPELINE_CACHE=$B/pipeline-cache-rebase.bin NX2NAVI_SHADER_CACHE=$B/shader-cache-rebase \
  NX2NAVI_XLATE=$B/$xl/nx2navi_xlate bash -c 'exec nixVulkanIntel build/v111/nx2navi.'$exe </dev/null >$log 2>&1 &
pid=$!
for ((i=0; i<1500; i++)); do sleep 1
  cur=$(grep -aoE 'present: frame [0-9]+' $log | tail -1 | grep -oE '[0-9]+$'); (( i % 10 == 0 )) && echo "frame ${cur:-0} of $frame"
  [ "${cur:-0}" -ge $frame ] && break
  grep -aqE 'FATAL|=== end' $log && break
  kill -0 $pid 2>/dev/null || break
done
kill -- -$pid 2>/dev/null; for ((i=0; i<600; i++)); do kill -0 -- -$pid 2>/dev/null || break; sleep 0.1; done; kill -9 -- -$pid 2>/dev/null
echo "== $mode (Cal's live play: fps 64.3, <60 76%, <50 26%, replay 10.0 ms, GPU 10.7 ms; lab texchurn 87.9 / 2% / 0% / 5.5 / 8.0)"
python3 -I $R/tools/rp-cmp.py $log
