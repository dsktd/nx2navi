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

## Regression: whiter picture, ~22 fps, write-back storm (2026-11-08, iteration log)

- Not the pow fix (hypothesis e): run-20261108-095800 (09:58, before fmz-pow existed) already shows the storm at frame
  1800 (334k syncs, 44.9 GB written back); Cal's play-112851 with the cache reverted too. Lab replay of
  input-20261108-112851.txt on shader-cache-lab (originals + nan-guard): frame 1800 256,630 syncs, 23.8 GB in, 25.3 GB
  written back, 25.6 fps. Replays of 112339 / 032149 diverge (stay at ~2495 pools) and show no storm.
- Cause (dump frame 2400, scratchpad passes-r851.txt): small compute dispatches (cs 147269d4b8cb3e70, 081e7b805f2a375d,
  ab89f96dc8e280e9, d72e565fd8fd8ab0, 5889b6908d68deaa: 1-2 workgroups, likely particle sims) write a storage buffer
  reached through a push pointer ("push pointer 0+0"). vk_exec_draw.c:1281 binds such a pointer with size 0 = "up to
  the end of the backing", so note_written records ~80 MiB (pool tail, e.g. 0x15b3de600 span 0x5351a00 although the
  table entry is +0x8800) per distinct start address. ~20 distinct tails per frame. vk_gpu_written then memcpy's the
  whole tail back into guest memory (> MERGE_MAX 4 MiB, so plain copy, no WB merge), which dirties the pages, which
  shadow_sync_pool copies in again, and the mirror re-uploads (55 MiB/frame): copied-in ~= written-back.
- The plain copy of a stale tail also puts old GPU bytes over whatever the CPU wrote there (the exact hazard the WB
  merge comment names for particle emitters): likely the brightening (particles/mist never cleared). Not verified.
- NX2NAVI_SHADOW=0: device lost (vkQueueSubmit2 -4) before frame ~300. Not usable. No other knob bounds the span.
- Fix needs the runtime (checkout): clamp a written pointer-SSBO's noted range to the shader's accessed size (or the
  pointer table entry's size, here +0x8800), or skip write-back for pointer-bound ranges. Upstream issue material.

## Wrong lighting at frame 2300 (Saria dialogue), dump-live walk (2026-11-08)

- Rectangle: absent from the lit scene up to pass 196 (ground ~0 outside the direct light). First seen in the half-res
  translucent target 12455 (rgba16f 720x405), written by pass 181 (prog 11469: vs cfe721e49a065f76, fs 3a6b76e478ecb654,
  2 draws, a large soft mist/fog card). Pass 198 (fs 3bdeddefe0d8de4b, the fog/translucent composite: froxels 878/880/882
  plus 12455/9212) adds it to the scene. The fs's alpha is _72.w * tex(slot 4).w * saturate(|depth diff|*0.2) * vs fade.
  Slot 4 is tex 665, NVN 0x4B RGTC2 (BC5), so .w is always 1: no texture edge fade, and only the vertex/depth terms remain.
  Whether hardware is the same (NVN RG swizzle gives .w = 1) is still open. The dump shows identity swizzle (2345).
  Shader files: shader-cache/ba68487f...spv and f1e9319f...spv (fs), 62b7b818...spv and 7bda918b...spv (vs).
- Glow/haze: pass 228 (fs 13253fa8bc1dcf47) = scene*M*c3[3].z + pow(bloom 240x135, c3[3].y), then ACES. The bloom is
  added at full weight, so the glow is that pow term plus HDR fairies at 62. Next: NX2NAVI_DUMP_UBO to read c3[3].
  Pass 231's lifted floor (0.15) is the sqrt encoding the upscaler stand-in squares, not haze.
- CS fallback: in this frame the only untranslated dispatch is the tensor upscaler (vk_tonemap stand-in, post-tonemap).
  It cannot add the rectangle or the bloom. Prewarm: 0 failed translations.
- A/B blocked: recording input-20261108-122846.txt now diverges into the pause menu at frame 2300 (129 passes, both
  lab-run and ab-live.sh, with NX2NAVI_SKIP_SHADERS=3a6b76e478ecb654). dump-live (12:31) did not diverge. Needs a fresh
  recording, or a dump frame before the divergence, before the skip test means anything.
- Retry alone (lab-run, flock, no other game): frame 2300 and frame 1900 both land in the pause menu (129 passes).
  So the divergence is not caused by overlapping runs. Most likely the replay starts from game state that has changed
  since 12:31 (save data or settings written by later runs). Needs a fresh recording from Cal's current save.
- Fresh recording input-20261108-125206.txt: replays are not deterministic. At frame 1900 three runs landed in three
  places (dense mist outdoors, a different camera, inside the Deku Tree). At frame 1400 every run is at the Saria dialogue
  (the dump-live scene) and is usable for A/B.
- Frame 1400 A/B: skipping 3a6b76e478ecb654 (mist card) leaves the rectangle, and so does skipping bc280fb2a7cc7e22
  (pass 179). Making the card's alpha read the BC5 G channel (private cache copy) changes nothing. So the rectangle is not
  the mist card. It is most likely floor geometry that only pass 198 (fog composite, fs 3bdeddefe0d8de4b) lights.
- Frame 1900 (mist scene) skip run: much less haze, but the camera differed, so this is not proof.
- Tonemap UBO (frame 1900, prog 39335, fs f450014def48f713): c4 colour matrix close to identity, pow 1.11, exposure 1,
  3D grading LUT. The values look like normal game settings; there is no sign of a broken exposure input.
- Note: ssbo 3 (0x25a4c7f00) guest bytes hold 0xFFFFFFFF (-nan) in words 12-27. These are guest bytes, not the GPU
  copy (the frame has no NaN), so this is probably an uninitialised fill that is never written back.

## Haze + slab, recording input-20261108-131323 (2026-11-08)

- Frame 1100 (presents) is in the hazy Kokiri area (219 passes); frame 300 is still the load menu. No NaN anywhere.
- Froxel chain: pass 76 (cs 758cfce40008b5f0, 9x5x7) injects density into tex 8088/r16f (max exactly 1.0, mean 0.27;
  the near slices are saturated at 1, the far ones are noise-shaped) plus two r11g11b10f in-scatter volumes. Pass 77
  (cs 1673eb18f482ce7c, 9x5x1) integrates along the depth into tex 881 (r16f, max 20.8, which reads as optical depth) and 878/880. No inf
  and no NaN, so nothing is clearly outsized apart from the saturated near density.
- A/B at frame 1100: skip mist card 3a6b76e4 -> haze and slab unchanged (cleared). Skip injection 758cfce4 -> haze
  gone, scene near black. Skip fog composite 3bdeddef -> haze gone, ground and slab black: only Link, fairies and roots
  stay lit.
- Reading: the haze is the fog in-scatter itself, layered on geometry that gets almost no ambient light of its own (same as the
  frame 2300 finding: ground ~0 outside the direct light). The slab is the rock face, which only the fog
  composite lights. Most likely the bug is missing ambient/probe lighting in the deferred lighting pass, not the fog shaders.
- FMZ: running fmz-pow-scan on the dump's sh_*.spv flags many shaders (fog composite 10 sites, integrator 2). The dump
  SPIR-V is the raw translator output, not the patched cache file (the cache names are not the SPIR-V's sha256), so
  this does not show that the fix is missing. Live cache has 23,649 .orig files, so fmz-pow is applied there.
  No new FMZ candidate was tested.
- Next: find the deferred ambient/SH-apply pass (readers of ssbo 0x25a4c7f00 at frame 1100) and check its ambient term.
  Also check FFMA.FMZ (the dot-product or SH-evaluation form, not only pow), since the translator ignores Fmz everywhere.

## Ambient: FMZ on ordinary multiplies (2026-11-08, frame 1100, input-20261108-131323)

- No deferred ambient pass: lighting is forward. Passes 169/171 (1440x810 r11g11b10f, 37 + 146 draws) shade the
  world; their fs bind the sky SH (ssbo slot 2 = 0x25a4c7f00+0xc0) plus cube 751, LUT 850, tex 7138/7169/7170. After
  pass 171 the ground is already 0 (min 0, 93k distinct values), before any fog. The fs use NClamp/NMax heavily, so a
  NaN from inf*0 is silently clamped to 0 = black, which is why the frame shows "no NaN".
- tools/fmz-all.py (new, sibling of fmz-pow.py): every scalar OpFMul and GLSL Fma gets FMZ semantics (0*x = 0, fma ->
  c). Writes via temp + rename, so it is safe in a hard-linked cache copy (cp -al shader-cache shader-cache-amb, 9 s).
- A/B, the 93 fs/vs of passes 169/171/181/182 only (265 cache files): opaque target min 0 -> 1.7e-4, distinct 93k ->
  760k; ground, rocks and moss are lit (yellow-green, sunlit). Final frame: the world shows through, fog still dense.
  CULPRIT: Fmz ignored on FMUL/FFMA in general, not only in pow.
- Same pass over all 298 frame shaders: unclear. One shader failed spirv-val (script aborted mid-list; skip-on-error
  needed) and the replay diverged indoors (204 passes). Not usable.
- Next: proper translator fix (honour Fmz in FMUL/FFMA/FMUL32I/FFMA32I emitters, patch series). The blanket pass is a
  diagnostic superset: it also changes multiplies that had no .FMZ (only matters for 0*inf/NaN, so low risk).
  Then re-check the fog density with the fix applied everywhere.

## Translator FMZ patch (2026-11-08): a no-op on this game

- patches/0002-xlate-honour-fmz.patch makes FMUL/FFMA/FMUL32I/FFMA32I with Fmz == Fmz emit (a==0||b==0) ? 0 : a*b
  (FFMA: ? c : fma). tools/build-xlate-private.py runs build_xlate.py with it applied. Not hooked into `just xlate`.
- It changes nothing: the shaders are sm86, and AmpereLowering.cs (Fmul/Ffma) throws on bit 81 (the FMZ half of the
  80-81 field) and copies only bit 80 (FTZ). 0 lowering failures over 44,156 shaders, so no game shader uses FMZ
  (docs/maxwell.md check 13 agrees: FMZ in 1 instruction). All 289 SPIR-V of frame 820 are byte-identical with and without.
- So the hardware's pow(0,0) and the fmz-all lighting win do not come from FMZ. The fmz-pow / fmz-all effect still has
  to be explained (candidates: MUFU.LG2/EX2 semantics on sm86, or a lowering detail). fmz-pow.py stays needed.
- A fresh cache (any translator, NX2NAVI_SHADER_CACHE empty or with a copy of in/) renders the world black at frames
  700/820/1100: the fog composite (fs 3bdeddef, pass ~169) writes 0, i.e. the raw pow NaN that fmz-pow fixes.
- Private full re-translate: copy the live in/ (44,156 stored inputs, 629 MB) into an empty cache; prewarm translates
  43,453 in 145 s with 16 translators, 0 failed.
- spirv-val: 8 of 289 frame shaders fail in base and fix alike (StorageImageReadWithoutFormat missing), pre-existing.

## Hot-reload + where the FMZ bisect stopped (2026-11-08, interrupted by host reboot)

- patches/0003-shader-hot-reload.patch (build 087f7bc): NX2NAVI_SHADER_RELOAD=1 reloads a rewritten cache <key>.spv in
  about 1 frame ("vk_pipeline: reload <key16> ok|failed"); touch build/v111/shot.req -> logs/shot-<n>.png. Tested on a
  private cache only. Each edit takes about 1-3 s, compared with about 60 s for a lab-run dump. The live cache was never touched.
- Recording input-20261108-131323 now replays into an indoor scene (map "1F") at frames 820/1100 (3 runs): it diverged,
  so lab A/Bs on it do not show the Kokiri ground. Bisect not started yet.
- Next: in Cal's live game (`NX2NAVI_SHADER_RELOAD=1 just play`, outdoors), map the 93 pass-169/171 shaders to cache
  keys (dump sh_*.spv == cache .spv/.orig by size+cmp). Then apply fmz-all to copies one shader at a time through the reload
  loop (temp + rename, keep .orig, restore after), then one site at a time. Then trace the inf/NaN operand (MUFU edge cases,
  the SH words 12-27 = 0xFFFFFFFF).

## Deku web, live hot-reload bisect (2026-11-08, play-20261108-141155)

- FMZ is cleared as the cause. fmz-all on the 172 drawn pixel shaders lights the room; reduced to one pixel shader (fb9bc087,
  multiply sites 513 + 538 together), which takes its SH L0 term from input location 1.w * 0.282095. A NaN guard on that
  input lights the room and an inf guard does not. The NaN comes from vs b295ba18 (out1.w = SH from storage buffer slot 0, words 13/21/25..., the
  sky-SH block 0x25a4c7f00). fmz-all on the vs does nothing; a NaN guard on its outputs lights the room.
- The block is accumulated by float atomic adds that the translator emulates as AtomicOr(0) + CAS loops (cs e9b99bf2 pass 23
  4x4x6, cs a806b657 pass 101 1x1x1). Neither pass stores or clears the block. Once the GPU copy holds NaN it stays NaN
  (NaN + x). tools/cas-nan-guard.py (old NaN -> 0 in the CAS add) on a806b657's 3 cache files (b51b2871, ef9d2a01,
  29fce94c) lights the whole room like the reference: ground metric 49 -> 234. Kept live; backups in build/v111/reload-bak.
- Still open: how the NaN enters on our side but not on hardware. Leads: (1) the guest bytes hold 0xFFFFFFFF in words
  12-27 and seed the GPU copy; (2) the game's per-frame reset of the block (CPU memset, or a GPU fill/copy) does not reach
  the GPU copy, a mirror/shadow sync gap for a GPU-written range. If (2) is right, the guarded sums would grow over time.
  Next: log the GPU copy of 0x25a4c7f00..+0x100 per frame (vk_dump buffer snap) with and without the guard, and trace
  the guest writes to that page.
- `just fmzpow` rewrites b51b2871 from its .orig and would drop the guard; run cas-nan-guard.py again after it.
