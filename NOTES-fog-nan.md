# Black picture at the first outdoor scene: NaN fog volumes (2026-11-08)

Chain (frame dumps, NX2NAVI_DUMP): scene lit and complete -> fog composite (full-screen draw sampling the froxel
volumes) writes zeros -> black. The froxel volumes are NaN because the fog light-injection compute (dispatch 8x9x12,
LocalSize 8x4x4, writes two 64x36x96 r11g11b10f volumes + one rg8) produces NaN in every computed froxel; the
temporal history then keeps it forever.

Ruled out with evidence: translator PRMT patch (was missing, fixed in the justfile, NaN persists); mesh path;
pipeline skips; constants c3/c4/c5 (dumped with NX2NAVI_DUMP_UBO=4096, all finite, no 1/0); the five-pointer table
and its resolution; the light-probe grid headers (s2: origin, cell size 64, dims 6x2x4; s3 strides 1/2/8 x16 B);
textures (per-column depth min/max; the 4x4 texture only gates flags).

Remaining: the per-cell (s5 @0x1af9c8680, 32 B records) and per-probe (s6 @0x1b1b58680, 128 B) records, read by the
shader through the pointer table. Lead: the runtime log says "shadow storage: CPU-visible pools are host-visible
copies of guest memory, not imports" and mirrors ~850 MiB; the probe heap (~150 MiB) is such a copy, kept current by
userfaultfd write-watch. Pages filled by file I/O or before the pool was first bound may never be flagged, so the
GPU copy holds stale bytes while guest RAM is right. A fixed garbage pattern NaNs every froxel; zeros would not.

Next steps:
1. A/B: `NX2NAVI_MEMORY=import` (vk_memory.c ~1247: pools imported as host memory, no mirror). Fog back => mirror
   sync misses those pages; then the no-checkout fix is NX2NAVI_MEMORY=import in the justfile's run/debug env.
2. Else one more dump with NX2NAVI_DUMP_BUF=0x1af9c8680:0x100 (first eight s5 records; expect packed u16 pairs and
   floats 0..64), then 0x1b1b58680:0x100 (probe 0).
3. Fallback only if the data is upstream's: SPIR-V isnan guard on the two stores (masks the bug, no fog).

Tooling: dumps go to build/v111/dump (NX2NAVI_DUMP=<frame> NX2NAVI_DUMP_DIR=... [NX2NAVI_DUMP_UBO=n]
[NX2NAVI_DUMP_BUF=addr:size, one range]); `just replay <recording> KEY=VALUE...` passes env. The shader's GLSL can be
regenerated with build/xlate/nx2navi_xlate (glsl_out) for program hash ddc04154cb30aecc....
