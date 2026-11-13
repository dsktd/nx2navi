#!/bin/bash
# direct.sh <exe> <tag> [secs]: one field-mid-standing run started directly on gamescope's second X display (not through
# Steam: for when the entry is blocked), cell.sh's pinned settings, stopped after secs (default 150). Out: runs/<tag>/
N=$HOME/nx2navi; B=$N/build/v111; exe=$1 tag=$2 secs=${3:-150}
pgrep -f "nx2navi\.[a-z0-9]+$" >/dev/null && { echo "direct: a game is running" >&2; exit 3; }
O=$N/runs/$tag; rm -rf $O; mkdir -p $O; cp -a $N/scn/field-mid-standing $O/profile
[ -e $B/pipeline-cache-$exe.bin ] || cp $B/pipeline-cache-deck.bin $B/pipeline-cache-$exe.bin
printf '%s\n' NX2NAVI_PIPELINE_CACHE=$B/pipeline-cache-$exe.bin NX2NAVI_PIPE_SKIP=strict NX2NAVI_INPUT_SCRIPT=$N/scn-stand.txt NX2NAVI_PROFILE_DIR=$O/profile NX2NAVI_DUMP_DIR=$O/dump \
    NX2NAVI_RUN_NAME=$tag NX2NAVI_TRACE=perf,present NX2NAVI_FPS_LIMIT=unlimited NX2NAVI_VK_PRESENT=immediate \
    NX2NAVI_FULLSCREEN=1 NX2NAVI_WINDOW_SIZE=1280x800 NX2NAVI_GAME_RES=window NX2NAVI_GAME_RES_MIN=720 NX2NAVI_GAME_RES_MAX=1080 \
    NX2NAVI_GAME_ASPECT=16:9 NX2NAVI_HDR=0 NX2NAVI_TEXTURE_DETAIL=low NX2NAVI_AA=game NX2NAVI_UPSCALER=fsr NX2NAVI_DLAA=0 NX2NAVI_LOW_END_GPU=0 NX2NAVI_OPERATION_MODE=docked NX2NAVI_ANISO=16 \
    NX2NAVI_PERF_OVERLAY=full NX2NAVI_EXE=$exe CELL_LOG=$O/run.log > $N/cell.env
DISPLAY=:1 XDG_RUNTIME_DIR=/run/user/1000 $N/play.sh & 
minav=999999
for ((i=0; i<secs; i++)); do sleep 1; av=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo); [ $av -lt $minav ] && minav=$av
  [ $av -lt 300 ] && { echo "direct: MemAvailable $av MiB, stopping"; break; }
  grep -aqE 'FATAL|=== end' $O/run.log 2>/dev/null && break; [ $i -gt 5 ] && ! pgrep -x nx2navi.$exe >/dev/null && break; done
hi=$(grep -aoE 'present: frame [0-9]+' $O/run.log | tail -1 | grep -oE '[0-9]+$'); st=$(python3 -I $N/stable.py $O/run.log 400)
pkill -x nx2navi.$exe; sleep 3; pkill -9 -x nx2navi.$exe
echo "$tag exe=$exe last=$hi settled=${st:-no} $(python3 -I $N/sum.py $O/run.log ${st:-1800} ${hi:-0}) minavail_mib=$minav"; grep -a 'FATAL\|device was lost' $O/run.log | head -3 | cut -c1-200
