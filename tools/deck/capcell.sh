#!/bin/bash
# capcell.sh <up|d5> <capture dir> <tag> [secs]: one capture-start standing run on the Deck (upstream 4fd70e3,
# NX2NAVI_CAPTURE_REPLAY; no boot-timed scn-stand.txt): the upstream reference (~/nx2navi/upstream/ocarina) or the
# patched entry's exe (play.env). Both read Cal's live build/v111/nx2navi.ini as the capture's settings.ini (a copy:
# cap-prep; no game folder's ini is touched). Started directly on gamescope's :1 like ab-up.sh. Measured from the
# replay's `ready` line + SKIPF (300) frames to the end (cap-sum). Out: runs/<tag>/
N=$HOME/nx2navi; B=$N/build/v111; U=$N/upstream; w=$1 cap=$(realpath "$2") tag=$3 secs=${4:-240}
pgrep -x ocarina >/dev/null || pgrep -f "nx2navi\.[a-z0-9]+$" >/dev/null && { echo "capcell: a game is running" >&2; exit 3; }
O=$N/runs/$tag; rm -rf $O; mkdir -p $O
python3 -I $N/cap-prep "$cap" $O --base $N/scn/field-mid-standing --ini $B/nx2navi.ini || exit 4
M="NX2NAVI_PROFILE_DIR=$O/profile NX2NAVI_CAPTURE_REPLAY=$O/cap NX2NAVI_CAPTURE_DIR=$O/cap/replays NX2NAVI_RUN_NAME=$tag NX2NAVI_TRACE=perf,present"
if [ $w = up ]; then exe=ocarina
  (cd $U; unset LD_PRELOAD LD_LIBRARY_PATH; env $M DISPLAY=:1 /nix/store/ynczmb6i3kjia50k0hv19biblhjdnly9-nixVulkanIntel/bin/nixVulkanIntel $N/libs.sh ./ocarina > $O/run.log 2>&1) &
else
  echo "$M CELL_LOG=$O/run.log" | tr ' ' '\n' > $N/cell.env; exe=nx2navi.$(. $N/play.env; echo $NX2NAVI_EXE)
  DISPLAY=:1 $N/play.sh &
fi
minav=999999
for ((i=0; i<secs; i++)); do sleep 1; av=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo); [ $av -lt $minav ] && minav=$av
  [ $av -lt ${LOWMEM:-300} ] && { echo "capcell: MemAvailable $av MiB, stopping"; break; }
  grep -aqE 'FATAL|=== end|capture: replay of .* stopped' $O/run.log 2>/dev/null && break; [ $i -gt 5 ] && ! pgrep -x $exe >/dev/null && break; done
pkill -x $exe; sleep 3; pkill -9 -x $exe
echo "$tag exe=$exe $(python3 -I $N/cap-sum $O/run.log ${SKIPF:-300}) minavail_mib=$minav" | tee -a $N/runs/cells.log
grep -a 'FATAL\|device was lost\|capture: replay' $O/run.log | head -4 | cut -c1-200
