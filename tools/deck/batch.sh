#!/bin/bash
# batch.sh <scenario> <last-frame> <reps> <tag>=<K=V,K=V...> ...: the arms interleaved (a b c a b c ...), 15 s rest
# between runs; each run is cell.sh <scenario> <tag>-<rep>. Summary lines land in runs/cells.log.
N=$HOME/nx2navi; sc=$1 hi=$2 reps=$3; shift 3
for ((r=1; r<=reps; r++)); do
  for arm; do tag=${arm%%=*}; kv=${arm#*=}; [ "$kv" = "$arm" ] && kv=""
    IFS=, read -ra e <<< "$kv"
    $N/cell.sh $sc $tag-$r $hi "${e[@]}"; sleep 15
  done
done
