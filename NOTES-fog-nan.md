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

## Fog NaN bisect (SPIR-V store probes, container, frame 1500)

Tool: scratchpad probe.py rewrites the img1 store composites (%5876 site 1, %10388 site 2) of sh_67ebcf9b12b90fbe; install.sh copies it over the 4 identical cache entries (backed up as .spv.orig).

baseline (originals) NaN 153108

## Stopgap verified (2026-11-08)

`tools/nan-guard.py` (wired as `just nanguard`, run after `just shaders`) wraps every vec4 image write of the fog
light-injection shader in NMax(texel, 0). Container replay of Cal's save, frame 1500: no NaN anywhere in the frame
(was ~153k channels), and the picture is back: Link, Navi, lanterns, HUD render. The whole injection output is now 0,
so there is no volumetric fog, and everything outside direct light is near black. Ambient light from the probe grid
seems to be missing as well, which points at the same defect in other shaders that read the probe data, not only
this one. The guard proves the cause; the real fix is the instruction the bisect will find (translator or RADV).
`just nanguard restore` puts the original SPIR-V back.

## Root cause found: FMZ ignored in pow (2026-11-08, iteration log)

Tool: tools/nan-probe.py (img0 store of the injection shader = NaN flags of up to 3 GLSL temps, temp_N = Nth Function
OpVariable; site 1 NaN 1.0 / finite 0.25; img1 guarded). Runs via scratchpad ab.sh, frame 1500.
- it1 ACO_DEBUG=noopt,novn,nosched,validateir: NaN unchanged (not an ACO optimisation).
- it3 probes temp_347 (1/weight sum) finite, temp_348 finite, temp_363 NaN.
- it4 temp_328 / temp_334 NaN = uintBitsToFloat(cp_s7.data[16] / [12]); s7 = NVN ssbo slot 0 @0x25a4c7f00 (+0xc0):
  the sky-ambient SH block, not the probe data. Guest bytes there are 0 (GPU results are never written back).
- it6 RADV_PERFTEST=cswave32: no change (the runtime already pins subgroups to 32). it7 NX2NAVI_MEMORY=import: no change.
- Writers of 0x25a4c7f00 (passes.txt "written"): pass 33 (4x4x6, words 32-35) and pass 93 (cs a806b657c39684bd,
  32x32x1, float atomic-add SH projection at c1[0]+...). Pass 93 does pow(clamp(x), c3[2].y) as
  %1856 = Log2; %1859 = OpFMul %1856 %1858 (c3[2].y); %1860 = Exp2. Maxwell compiles pow with FMUL.FMZ (0*inf = 0 so
  pow(0,0) = 1); Ryujinx decodes Fmz (InstDecoders.cs) but no emitter uses it, so SPIR-V gives -inf*0 = NaN. One NaN
  frame poisons the accumulated SH for good; the fog injection and every ambient-SH reader then go NaN/black.
- it8 tools/fmz-pow.py on pass 93's 3 cache files only (fog shader unguarded original): NaN 0 in the whole frame,
  injection max ~1200-2700, picture lit with fog and ambient.
- it9 fmz-pow on all 105 frame shaders with a variable-exponent pow (350 cache files, .orig kept): NaN 0, same picture.
Fix: tools/fmz-pow.py rewrites OpFMul(Log2 result, y) feeding Exp2 into (a==0||b==0) ? 0 : a*b. It must be rerun
after `just shaders` re-translates (cache-wide scan is slow: 391k files; frame-scoped list in scratchpad powcache.txt).
Proper fix: a translator patch in the justfile's patch series honouring Fmz in FMUL/FFMA (and FMUL32I/FFMA32I).
