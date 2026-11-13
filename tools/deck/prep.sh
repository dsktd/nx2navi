#!/bin/bash
# prep.sh [force]: build every pipeline of ~/nx2navi/lists/pipeline-list-merged.bin once into RADV's disk cache
# (build/v111/mesa-cache), in chunks of $CHUNK records (default 3000), one process a chunk, so no process keeps more
# than a chunk's pipelines in memory. A stamp (exe, Mesa, list) skips the work when nothing changed. Log: prep/prep.log
N=$HOME/nx2navi; B=$N/build/v111; P=$N/prep; EXE=${NX2NAVI_EXE:-deck2}; LIST=$N/lists/pipeline-list-merged.bin
MESA=/nix/store/ynczmb6i3kjia50k0hv19biblhjdnly9-nixVulkanIntel
key="$(sha256sum $B/nx2navi.$EXE $LIST | cut -c1-16 | tr '\n' ' ')$MESA"
[ "${1:-}" != force ] && [ "$(cat $P/stamp 2>/dev/null)" = "$key" ] && { echo "prep: up to date"; exit 0; }
exec 9>"$N/.game.lock"; flock -n 9 || { echo "prep: a game is running" >&2; exit 3; }
mkdir -p $P; rm -f $P/chunk-*.bin $P/seed-pipeline-keys.bin $P/seed-pipelines-running.txt
python3 -I - $LIST $P ${CHUNK:-3000} <<'PY' || exit 4
import struct, sys
d = open(sys.argv[1], 'rb').read(); n = int(sys.argv[3])
assert d[:8] == b'NX2NPLST'
ver, alen, klen = struct.unpack_from('<III', d, 8)
keys = d[20 + alen:20 + alen + klen]
magic, kver, rec = keys[:8], *struct.unpack_from('<II', keys, 8)
body = keys[16:]; total = len(body) // rec
for i in range(0, total, n):
    open('%s/chunk-%03d.bin' % (sys.argv[2], i // n), 'wb').write(keys[:16] + body[i * rec:(i + n) * rec])
print('prep: %d pipelines in chunks of %d' % (total, n))
PY
cd $B; : > $P/prep.log
for c in $P/chunk-*.bin; do
  cp $c $P/seed-pipeline-keys.bin
  env -u LD_PRELOAD -u LD_LIBRARY_PATH DISPLAY=${DISPLAY:-:1} XDG_RUNTIME_DIR=/run/user/$(id -u) RADV_DEBUG=nogpl \
    NX2NAVI_EXEFS=$N/build/extracted/v111/exefs NX2NAVI_ROMFS=$N/build/extracted/v111/romfs \
    NX2NAVI_XLATE=$B/xlate-play33/nx2navi_xlate NX2NAVI_SHADER_CACHE=$B/shader-cache-rebase \
    NX2NAVI_PIPELINE_CACHE=$P/pipeline-cache.bin NX2NAVI_RUN_NAME=prep \
    /nix/store/ynczmb6i3kjia50k0hv19biblhjdnly9-nixVulkanIntel/bin/nixVulkanIntel $N/libs.sh ./nx2navi.$EXE --prepare-pipelines >> $P/prep.log 2>&1
  echo "prep: ${c##*/} rc $? $(grep -a 'listed pipelines:' $P/prep.log | tail -1 | cut -c1-200) avail $(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo) MiB"
  rm -f $P/pipeline-cache.bin $P/pipeline-cache-play.bin
done
rm -f $P/chunk-*.bin $P/seed-pipeline-keys.bin
echo "$key" > $P/stamp; echo "prep: done, mesa-cache $(du -sh $B/mesa-cache | cut -f1)"
