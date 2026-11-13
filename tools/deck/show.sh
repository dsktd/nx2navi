#!/bin/bash
# show.sh [exe] [scenario]: start the game in the foreground through the Steam entry and leave it running: exe (default
# deck4) from a copy of a scenario save (default field-mid-standing = Hyrule Field), loaded by scn-stand.txt, perf overlay
# full; every other setting is nx2navi.ini's. Log: runs/show/run.log. Stop: pkill -x nx2navi.<exe>
N=$HOME/nx2navi; B=$N/build/v111; exe=${1:-deck4}; sc=${2:-field-mid-standing}
exec 9>"$N/.game.lock"; flock -n 9 || { echo "show: a game is running" >&2; exit 3; }
pgrep -f "nx2navi\.[a-z0-9]+$" >/dev/null && { echo "show: a game is running" >&2; exit 3; }
O=$N/runs/show; rm -rf $O; mkdir -p $O; cp -a $N/scn/$sc $O/profile
[ -e $B/pipeline-cache-$exe.bin ] || cp $B/pipeline-cache-deck.bin $B/pipeline-cache-$exe.bin 2>/dev/null
printf '%s\n' NX2NAVI_EXE=$exe NX2NAVI_PIPELINE_CACHE=$B/pipeline-cache-$exe.bin NX2NAVI_INPUT_SCRIPT=$N/scn-stand.txt \
  NX2NAVI_PROFILE_DIR=$O/profile NX2NAVI_RUN_NAME=show-$exe NX2NAVI_PERF_OVERLAY=full CELL_LOG=$O/run.log > $N/cell.env
exec 9>&-
DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus steam steam://rungameid/16393611824920002560 >/dev/null 2>&1 &
for ((i=0; i<${WAIT:-60}; i++)); do sleep 1; pid=$(pgrep -x "nx2navi.$exe" | head -1); [ -n "$pid" ] && break; done
[ -n "$pid" ] || { echo "show: the Steam entry did not start the game" >&2; rm -f $N/cell.env; exit 4; }
echo "show: nx2navi.$exe pid $pid"
