#!/bin/bash
# cell.sh <scenario> <tag> <last-frame> [KEY=VAL...]: one standing run on the Deck (save load via scn-stand.txt), ended
# 10 s after the frame time settles (LONG=1: at <last-frame>), started through the Steam entry in the foreground; then
# fps / 1% low / interval / replay / gpu over present frames LO(default 1800)..last. Out: ~/nx2navi/runs/<tag>/{run.log,sum.txt}
N=$HOME/nx2navi; B=$N/build/v111; sc=$1 tag=$2 hi=$3; shift 3; lo=${LO:-1800}
exec 9>"$N/.game.lock"; flock -n 9 || { echo "cell: a game is running" >&2; exit 3; }
pgrep -f "nx2navi\.[a-z0-9]+$" >/dev/null && { echo "cell: a game is running" >&2; exit 3; }
O=$N/runs/$tag; rm -rf $O; mkdir -p $O $B/logs; cp -a $N/scn/$sc $O/profile
cd $B
{ for kv in NX2NAVI_PIPE_SKIP=strict NX2NAVI_INPUT_SCRIPT=$N/scn-stand.txt NX2NAVI_PROFILE_DIR=$O/profile NX2NAVI_DUMP_DIR=$O/dump \
    NX2NAVI_RUN_NAME=$tag NX2NAVI_TRACE=perf,present NX2NAVI_FPS_LIMIT=unlimited NX2NAVI_VK_PRESENT=immediate \
    NX2NAVI_FULLSCREEN=1 NX2NAVI_WINDOW_SIZE=1280x800 NX2NAVI_GAME_RES=window NX2NAVI_GAME_RES_MIN=720 NX2NAVI_GAME_RES_MAX=1080 \
    NX2NAVI_GAME_ASPECT=16:9 NX2NAVI_HDR=0 NX2NAVI_TEXTURE_DETAIL=low NX2NAVI_AA=game NX2NAVI_UPSCALER=fsr NX2NAVI_DLAA=0 NX2NAVI_LOW_END_GPU=0 NX2NAVI_OPERATION_MODE=docked NX2NAVI_ANISO=16 \
    NX2NAVI_PERF_OVERLAY=full NX2NAVI_EXE=${EXE:-deck2} CELL_LOG=$O/run.log "$@"; do echo "$kv"; done; } > $N/cell.env
exec 9>&-   # play.sh takes the one-game lock itself
DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus steam steam://rungameid/16393611824920002560 >/dev/null 2>&1 &
for ((i=0; i<60; i++)); do sleep 1; pid=$(pgrep -x "nx2navi.${EXE:-deck2}" | head -1); [ -n "$pid" ] && break; done
[ -n "$pid" ] || { echo "cell: the Steam entry did not start the game" >&2; rm -f $N/cell.env; exit 4; }
minav=999999; maxgtt=0; D=/sys/class/drm/card0/device
for ((i=0; i<${TMO:-600}; i++)); do sleep 1
  av=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo); [ $av -lt $minav ] && minav=$av
  g=$(( ($(cat $D/mem_info_gtt_used) + $(cat $D/mem_info_vram_used)) / 1048576 )); [ $g -gt $maxgtt ] && maxgtt=$g
  [ $av -lt ${LOWMEM:-700} ] && { echo "cell: MemAvailable $av MiB, stopping" >> $O/run.log; break; }
  cur=$(grep -aoE 'present: frame [0-9]+' $O/run.log | tail -1 | grep -oE '[0-9]+$'); [ "${cur:-0}" -ge $hi ] && break
  # short standing cell: once the frame time has settled (stable.py), take SECS (10) more seconds and stop
  if [ -z "${LONG:-}" ] && [ $((i % 2)) = 0 ] && [ "${cur:-0}" -ge ${MINF:-400} ]; then
    st=$(python3 -I $N/stable.py $O/run.log ${MINF:-400}); [ -n "$st" ] && { lo=$st; sleep ${SECS:-10}; hi=$(grep -aoE 'present: frame [0-9]+' $O/run.log | tail -1 | grep -oE '[0-9]+$'); break; }
  fi
  grep -aqE 'FATAL|=== end' $O/run.log && break; kill -0 $pid 2>/dev/null || break
done
[ -n "$SHOT" ] && { touch $B/shot.req; sleep 3; }
kill $pid 2>/dev/null; for ((i=0;i<300;i++)); do kill -0 $pid 2>/dev/null || break; sleep 0.1; done; kill -9 $pid 2>/dev/null
python3 -I $N/sum.py $O/run.log $lo $hi > $O/sum.txt; echo "$tag $sc $(cat $O/sum.txt) minavail_mib=$minav maxgpu_mib=$maxgtt swapused_mib=$(free -m | awk '/Swap/{print $3}') sys=$(cat /sys/module/udmabuf/parameters/size_limit_mb)/$(cat /sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference)/$(cat /sys/class/drm/card0/device/power_dpm_force_performance_level)" | tee -a $N/runs/cells.log
