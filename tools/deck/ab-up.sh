#!/bin/bash
# ab-up.sh <up|d5> <tag> [secs]: one field-mid-standing run of the upstream reference (~/nx2navi/upstream/ocarina) or
# the patched entry's exe (play.env), each with its own defaults and Cal's nx2navi.ini (the upstream folder gets a copy
# for the run; its default ini is put back after). Started directly on gamescope's :1 like direct.sh. Out: runs/<tag>/
N=$HOME/nx2navi; B=$N/build/v111; U=$N/upstream; w=$1 tag=$2 secs=${3:-170}
pgrep -x ocarina >/dev/null || pgrep -f "nx2navi\.[a-z0-9]+$" >/dev/null && { echo "ab-up: a game is running" >&2; exit 3; }
O=$N/runs/$tag; rm -rf $O; mkdir -p $O; cp -a $N/scn/field-mid-standing $O/profile
M="NX2NAVI_INPUT_SCRIPT=${SCRIPT:-$N/scn-stand.txt} NX2NAVI_PROFILE_DIR=$O/profile NX2NAVI_RUN_NAME=$tag NX2NAVI_TRACE=perf,present"
if [ $w = up ]; then
  cp $U/nx2navi.ini $O/ini.default; [ -n "$DEFAULT_INI" ] || cp $B/nx2navi.ini $U/nx2navi.ini; exe=ocarina
  (cd $U; unset LD_PRELOAD LD_LIBRARY_PATH; env $M DISPLAY=:1 /nix/store/ynczmb6i3kjia50k0hv19biblhjdnly9-nixVulkanIntel/bin/nixVulkanIntel $N/libs.sh ./ocarina > $O/run.log 2>&1) &
else
  echo "$M CELL_LOG=$O/run.log" | tr ' ' '\n' > $N/cell.env; exe=nx2navi.$(. $N/play.env; echo $NX2NAVI_EXE)
  DISPLAY=:1 $N/play.sh &
fi
minav=999999
for ((i=0; i<secs; i++)); do sleep 1; av=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo); [ $av -lt $minav ] && minav=$av
  [ $av -lt ${LOWMEM:-300} ] && { echo "ab-up: MemAvailable $av MiB, stopping"; break; }
  grep -aqE 'FATAL|=== end' $O/run.log 2>/dev/null && break; [ $i -gt 5 ] && ! pgrep -x $exe >/dev/null && break; done
hi=$(grep -aoE 'present: frame [0-9]+' $O/run.log | tail -1 | grep -oE '[0-9]+$'); st=$(python3 -I $N/stable.py $O/run.log 400)
pkill -x $exe; sleep 3; pkill -9 -x $exe
[ $w = up ] && cp $O/ini.default $U/nx2navi.ini
echo "$tag exe=$exe last=$hi settled=${st:-no} $(python3 -I $N/sum.py $O/run.log ${st:-1800} ${hi:-0}) minavail_mib=$minav" | tee -a $N/runs/cells.log
grep -a 'FATAL\|device was lost' $O/run.log | head -3 | cut -c1-200
