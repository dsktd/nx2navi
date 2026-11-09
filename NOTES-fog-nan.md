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

## Sky-SH block: root cause of the build-up (2026-11-08, NX2NAVI_WATCH, play-20261108-150423)

- The game zeroes 0x25a4c7f00 on the CPU each frame (guest w13 drops to 0 between parts). The watch log shows
  gpu-pending (record) -> cpu-dirty on the page -> cpu->shadow copies only 0x25a4c7fc0+0x40: the block itself is
  skipped, because vk_mem_shadow_sync runs after the part was recorded and that part's own GPU writes were already in
  the pending list. So the zero never reached the shadow, the atomics added to last frame's sums, and the fence
  wrote the stale sums back over the CPU's zero. A NaN frame stuck for good; without NaN the sums grew (white-out).
- ef1f5c1 is not involved (same skip without it).
- Fix: patches/0004 (build f33ed65): skip only submitted parts' ranges that the next part does not write again.
- Stopgap meanwhile: tools/cas-reset.py --abs 32,33,34,35 on a806b657 (live with cas-nan-guard; guarded copies in
  build/v111/reload-bak/guarded). Remove both after the fix is verified: restore build/v111/reload-bak/*.spv.

## Validation sweep and AO event waits v3 (2026-11-09, overnight lab)

- Validation (#134): `LAB_VALIDATE=1` (sync) never gets past boot: the game stalls with every thread in futex. Bisected:
  each check alone passes, and core + check_shaders stalls too, so lab-run now defaults check_shaders off. Sync validation
  still stalls on its own, so no SYNC-HAZARD data yet. `LAB_VALIDATE=core`, 131323 to frame 1100 and the castle spot
  (frame 1500 via load-slot01.txt, which works): only two IDs, 6 messages each:
  1. `VUID-vkCmdCopyImageToBuffer-srcImageLayout-00189`: copy from an image in GENERAL that the layer last saw in
     ATTACHMENT_FEEDBACK_LOOP_OPTIMAL (feedback-loop layout is not transitioned back before a readback copy).
  2. `VUID-VkImageViewCreateInfo-usage-02275`: R8G8B8A8_SRGB views inherit STORAGE usage that the format can't support
     (needs a usage-list view or no STORAGE on sRGB views).
  Earlier spirv-val errors with check_shaders on: missing StorageImageReadWithoutFormat capability, and fs inputs at
  locations 9/11/13 that the vs never writes (`VUID-RuntimeSpirv-OpEntryPoint-08743`).
- `LAB_HANG=1` to 1100: `radv: GPU hang detected` at about 27 s, then radv segfaults (+0xfae0c) and writes no report.
  Without hang mode the same replay runs cleanly, so this is probably a syncshaders timeout, not a real hang.
- AO v2's flicker: ew_drain checked the first wait *after* the cut (at0 = op after the wait), so every held part was
  released in the same call (log: `age 0`). v2 only cut submissions. Per frame, three queues (5eb, 640, 6aa) wait on
  event c8000, which queue 134133020's last submission signals; that submission itself waits on 38000/38004
  (alternating, double-buffered, no recorded signaller) before it signals.
- v3 (patch 0016): held parts wait on their own cut, and the signaller is cut after its signal. Dark frames (whole scene
  about 7% darker, HUD unchanged; not AO: skipping 561cf523 kept them) went from ~15 to 0-1 per 190 frames. AO reads the
  current depth (pass 0243 depth, then 0249 AO; off: AO 0199 before depth 0259). It is still off: one residual dip, and a
  device lost at the castle spot with waits=1. Next: trace the castle spot (`NX2NAVI_EVENT_WAITS=trace`) for a wait or
  signal inside a called command buffer (the walk only ends a part at depth 0).

## Gray close-LOD bushes (#138), 2026-11-09 night

Symptom: bushes and topiaries show bare gray branches up close; green from afar in Hyrule Field. Earlier cleared: the
mesh path (NX2NAVI_MESH=0, trap procs never called), the alpha test (discard removed from the 5 prepass alpha-test
shaders: still bare), render-condition skips (NX2NAVI_LOG_RCOND=1: draws skipped 0 at the castle frames), pipeline skips.

- The field frame (castle spot, frame 2400, `NX2NAVI_DUMP_DRAWS=1`, patch 0017) issues **no indirect draws at all**
  (memory traffic class "indirect" 0.000 in every pool class) and almost no instanced ones, so a GPU-built instance
  list or indirect count is not the mechanism. The 14 "0x0x0" dispatches are indirect *compute* (op_dispatch_ind).
- Cal's current slot save (`build/v111/profile`, copied) loads in the Hyrule Castle courtyard with a bare arched
  topiary 15 m ahead (frame 1500) and a conical one beside the fence after a backward walk (frame 2000): both bare at
  15-40 m. In Hyrule Field the trees at 50-100 m are bare and the ones at the castle (~300 m) have foliage.
- Candidate cause (patch 0018, untested): `vk_pipeline.c`'s vertex format table had no entry for the RGBX family
  (0x6D-0x78), 8-bit sRGB (0x37/0x38) and BGRX8; an attribute with such a format read the zero binding (0, 0, 0, 1)
  silently, which collapses leaf cards (corner offsets/sizes) while the branch mesh (common formats) draws fine. The
  patch maps them and logs an attribute still without a mapping.
- Blocked: from 00:00 every lab replay lost the device ~26 s after start, the game's and the gpu-display compositor's
  contexts both "innocent", also with the stock binary, RADV syncshaders and core validation, and regardless of the
  frame reached (time-based, not content). 23:44-23:58 seven castle/field replays in a row had passed. Not understood.
- Replay housekeeping: a killed replay leaves `pipeline-cache.bin.<pid>.<tid>.tmp` (4 GB each) in build/v111; 80 stale
  ones were removed. Scripted sticks are ±32767 (LSTICK 0 30000 = forward); ticks run ~290 ahead of presents by 1500.
- Scratch: input scripts and shots in the session scratchpad `bush/` (walk*.txt, back1.txt, cal1/, back1/).

Round 2 (2026-11-09 midday, lab, Cal's slot save at frame 1500 = castle courtyard, bare arched topiary 15 m ahead):
- Cleared: **occlusion culls.** The game resets/reports SAMPLES_PASSED 3-8 times a frame and its CPU reads the counts
  back (vk_exec_xfer.c: a 0 culls what the proxy tested). Patch 0020 adds `NX2NAVI_LOG_OQ=1` (one line per report:
  address, queries, sum, running count; at this spot 201k of 327k reports are 0, the rest 1/118/122/1638...) and
  `NX2NAVI_OQ_FORCE=<n>` (every report writes n). With OQ_FORCE=100000 the frame gains 5 passes (the culled objects
  come back; the butterflies vanish, which the force also changes) but the topiary stays bare.
- Cleared: the 0x4240 `c6` block at 0x25e92d300 shared by the vegetation vertex shaders (dumped with
  `NX2NAVI_DUMP_BUF=0x25e92d300:0x4240`): no NaN/inf, plausible values (c6[42] = 15, 0.625, 10.4, 0).
- Cleared earlier today: patch 0018 (vertex formats). Texture bindings of the alpha-tested prepass pipes look sane
  (BC1 sRGB RGBA = vk 134, BC3 138, BC4 139, BC7 146; swizzle 2345 identity; mirrored 1, uploads 1).
- Open lead: the vegetation vertex shaders (vs 5d33dc481e2771ac, fc33005113f12654, dbfce8684f95af3b; fs 099b152e1f417577
  and 7bd626f1f68fd3ff, pass 0138 pipes 4-6, 8-10 at frame 1500) sample **two vertex textures**: a BC4 512x512 noise
  (tex 2388) and a **512x512 rgba16f texture at 0x2642f3000 (tex 856) that nothing writes in the castle frames**
  (`mirrored 0 gpu_owned 0 uploads 0` at frames 1500 and 2000; 14 indirect compute dispatches read it too). In the
  field frame 2400 the same texture is the target of a 512x512 render pass (pass 0154, 3 draws, vs ef1a2c82 fs
  5b540a50) and has `gpu_owned 1`. Its sample feeds the card positions (vs5d33 lines 680-700: c6[36]-derived
  coordinates, NaN-guarded, Lod 0). `init_image` zero-clears a new non-aliased image when `NX2NAVI_FIX_ZERO` is on
  (default), but an image aliasing pool memory is not cleared, so this one may hold other textures' bytes here while
  the hardware memory is whatever the game put there. Next: dump the image (bind it as a dump target, or
  `NX2NAVI_WATCH=0x2642f3000:0x200000`), check whether it aliases pool memory, and A/B a forced zero clear of it; and
  find why the 512x512 pass does not run at the castle (the far castle trees have foliage, the 50-100 m ones do not,
  so the texture alone may not be the whole story).
- Lab output of this round: `.lab/bush-near2`, `bush-oqlog`, `bush-oqforce`, `bush-c6` (dumps with draw lists).

Round 3 (2026-11-09 13:25-14:00 UTC, lab, live profile, `load-slot01.txt` frame 1500 = the same courtyard; `.lab/bush-r3-castle`,
`bush-r3-castlelog`, `bush-r3-field`):
- **The round 2 lead is closed: the 512x512 rgba16f vertex texture (0x2642f3000, tex 856) is live and valid at the castle.**
  Dumped with `NX2NAVI_DUMP_TEX=856`: `pass_0002_tex856_512x512x1_97_rgba16f.png` is a top-down map of the courtyard
  (x -0.12..0.13, y -0.02..0.25, z = w = 0, 255k distinct values, no NaN), not zeros and not another texture's bytes.
  `NX2NAVI_WATCH=0x2642f3000:0x200000` logged no CPU write, fill or write-back in 1500 frames: the GPU owns it.
- Its writer is **compute, not a render pass**: `NX2NAVI_DUMP_LOG=1` (every pass from frame 1 to the dump frame) shows cs
  `27b283823816c23a` (64x64x1, img slot 2 store) writing 0x2642f3000 on every **odd** frame and 0x2648f6000 on even frames
  (ping-pong; slot 0 reads the other, slot 1 an rg16f 512x512, slot 3 a third rgba16f), first filled by cs `a56a8e3741233d71`
  at frame 785 (after the area load). Round 2 dumped frame 1500 (even) and so saw only the read. The dump's
  `gpu_owned 0 written-since 0` flags do not count compute image stores, so they are no evidence of "never written".
- What vs 5d33 does with it (SPIR-V, `scratchpad/vs5d33.dis`): samples xy only (`%406` shuffle 0 1), bend amount
  `x*x + y*y` (`%583`) and the two components scaled by `%143` under a flag: a push/bend field (grass bending under Link),
  so even a stale or zero texture would only straighten the cards, never remove the leaves.
- Replays drift again: `input-20261108-131323.txt` (the 11-08 field recording) on the live profile loads the castle slot and
  lands at the castle gate at frame 2400 (`bush-r3-field/final.png`); its frame 2400 has no 512x512 render pass either and
  tex 856 holds the same kind of map. A field reference needs the 11-08 profile copy (`lab-profile-flicker`;
  not run this round: the lab lock was held by a #128 replay).
- Where this leaves #138: cleared are the mesh path, alpha test, render conditions, vertex formats (0018), occlusion culls
  (0020), the c6 block and now the vertex textures' data. Not yet looked at: the **fragment** side of the LOD pipes (fs
  099b152e / 7bd626f1: alpha-test threshold vs. the sampled BC4 alpha, `discard` paths), the per-pipe draw counts of pass
  0138 against a field frame with leaves (`tools/dump-draws diff`), and whether the close-LOD leaf cards are drawn at all
  (an instance count or indirect count of 0 from one of the 14 indirect compute dispatches that read tex 856).

## VRAM pressure in the heavy field scene (#132), 2026-11-09 night, log analysis only

Cal's play-20261108-195849.log, frames 10500-11300 (36-46 fps, `vram 16414-17034 of 16378 MiB`, re-uploads 300-425
per 60 frames at 60-80 MiB and 23-37 ms, "texture 7-9%" of the render thread). The `mem: vram frame 10800` line
says what fills the card: VMA blocks 15894 MiB (allocations 15160: 730 MiB fragmentation), of which textures live
7769 = 6503 MiB, **textures released 2004 = 7226 MiB**, mirrors 331 = 925 MiB; the rest (~500 MiB) is buffers,
and the ~600 MiB over the VMA total is the driver's and the compositor's. Pipeline and shader caches live in RAM
(`ram working set 8.6 GiB`), not VRAM. The mirrors are small; the "stays imported" fallback hit only 4 pools at
frames 1800-2400 (14.1-15.1 GiB in use), so pools are not the problem either.

The released list is the filler: `vk_texture.c` keeps up to RELEASED_MAX 2048 released entries (FIFO) for take-back,
and a released entry averages 3.6 MiB (live ones 0.84 MiB): these are render targets and large decoded textures. The
VRAM-pressure sweep (`NX2NAVI_TEX_VRAM_PRESSURE`, 90%, 32 per 8 submits) only drops *mirrored* entries the GPU never
wrote, so it cannot touch those render targets; it drops the small sampled textures instead (181-448 per 60 frames),
which the game binds again a few frames later: that is the re-upload storm (309 re-uploads, 81 MiB, 34 ms at frame
10800) while the released count stays pinned at ~2000 and 7-8 GiB. From frame 6600 on the released set is 7.3-8.2 GiB
for the rest of the session. In short: the pressure sweep evicts the cheap-to-keep things and keeps the expensive ones.

Fix (patch 0019, build 187857e, in `nx2navi.new`, **not swapped**, default off): `NX2NAVI_TEX_RELEASED_MIB=<n>` caps
the own memory of the released list; past it, each release drops the oldest entries, exactly what RELEASED_MAX already
does by count (so a dropped render target that the game takes back comes back empty, the same as today past 2048
entries; the pressure sweep's black-flash caveat is about dropping *recent* ones). Suggested first value: 3072 (a 3 GiB
released set leaves ~4 GiB headroom, so the 90% sweep should rarely trigger and the re-uploads should fall to the
10-30 of frames 1200-6000). Check in the log: `released textures kept` (count), `mem: vram frame` released MiB,
`texture re-uploads`, `vram N of 16378`. If the heavy scene then shows black flashes or "left uninitialised" aliases
rising, raise the value (4096) or make the cap skip entries released fewer than N submits ago (not built).
Alternative not built: let the pressure sweep drop non-mirrored entries older than a few frames.

## fmz-pow after f33ed65: verdict (static, 2026-11-09)

What `tools/fmz-pow.py` guards: pow(x, y) with a variable y, compiled as Log2 -> OpFMul -> Exp2; it rewrites the
multiply to (a == 0 || b == 0) ? 0 : a * b, so pow(0, 0) = 1 and pow(0, y) = 1 instead of NaN (-inf * 0). The cache
holds 23,649 `.orig` files = the shaders it touched. Where the NaN came from: pass 93's SH projection
(cs a806b657, `pow(clamp(x), c3[2].y)`) fed NaN into the sky-SH block 0x25a4c7f00 **once**, and the block then kept it
because the shadow sync skipped the CPU's per-frame zeroing of that block (the real bug, fixed by patch 0004 /
f33ed65). With the zeroing in place a NaN frame is flushed the next frame, so the permanent black/white-out is gone
either way. What fmz-pow still changes: any frame in which pow(0, 0) is really evaluated (an SH weight exactly 0
with exponent 0) renders that frame's affected pixels/froxels black or NaN-clamped. Whether such frames exist at
all is the open question: the translator FMZ patch was a no-op (no game shader carries FMZ), so the hardware's
pow(0, 0) = 1 must come from MUFU.LG2/EX2 semantics or a lowering detail, which the fix does not model. Verdict:
**probably obsolete as a stopgap for the permanent fault, not proven harmless to remove**: a fresh cache was only
tried before f33ed65 (black world at frames 700/820/1100), never after.

Test plan (GPU back, Cal not playing): no live cache is touched.
1. `cp -r --reflink=auto build/v111/shader-cache /path/scratch/cache-fresh`, then `find /path/scratch/cache-fresh -name '*.orig' | while read o; do mv "$o" "${o%.orig}"; done` (the originals back: unpatched SPIR-V, no re-translation needed). Keep `in/`.
2. Replay A (patched, current): `tools/lab-run input-20261108-131323.txt 1100 fmz-on` and the castle slot
   `load-slot01.txt 1500 fmz-on-castle` (both with `LAB_EXE=nx2navi`, the running binary, patches 0001-0016).
3. Replay B (fresh): the same two with `NX2NAVI_SHADER_CACHE=/path/scratch/cache-fresh` in the env (lab-run passes
   env through; add it to `envs`), plus 2000 frames of the castle walk (`bush/back1.txt`) for a longer soak.
4. Compare: the dump's NaN count (`tools/nan-probe.py`-style scan of the dumped targets, or the lab's `dump` summary),
   the opaque target min/mean, the ground brightness metric from the Deku-web bisect (49 vs 234), and the shots side by
   side. Pass = no NaN, same picture within noise at both frames and no darkening over the soak.
5. If B passes: drop `fmzpow` from `just shaders` and move fmz-pow.py to the obsolete list; if B fails at a single
   frame only, keep fmz-pow and note the shader (the test shows which pass goes NaN).

## #128 intro dialogue too early at 240 fps: static pass (2026-11-09, no GPU)

Symptom (Cal): fps_limit 240, New Game: the intro's narration/voice lines overlap (trigger early); movie, audio and
gameplay speed are right. Static analysis of main 1.1.1 only (capstone disassembly of the whole .text, 15.8M
instructions, plus the lifted C). **Culprit not identified; no patch written.** What is established:

- Frame producer: the framework update main+0x6e6be0 (`this` = update object, no direct callers: reached through a
  pointer). s8 = frames per update (ostep: page +256); `this+0xd50` int32 += 1 per update (ldadd), `this+0xd58`
  double += s8, then main+0x3b4e300(mgr, s8) fills the time manager **[main+0x4c7e890]: +0x10 frames, +0x14 1/frames,
  +0x18 seconds (= frames * [main+0x3e4066c]), +0x1c int32 rate = round(60/frames); gameplay {frames, 1/f, s, 60/f}
  at +0x0..+0xc = base(+0x1c0) * frames * factor; 6 categories at +0x20 + 0x30*i (16 B each) from the 16 factors at
  +0x140 picked by the nibbles of +0x1c4. A listener at mgr+0x1c8 (GameSpStepRateMgr, init main+0xec7a10, heap
  "GameSpStepRateMgrHeap", vtable main+0x49a36f8) is called each step. `+0xd50` has no reader but an accessor
  (main+0x128c840, `!= 0`); `+0x1c` has no direct reader anywhere.
- Cleared (all take the manager's patched values): every reader of +0x10 (91 sites), +0x18 (25) and +0x0 (21); the
  event-flow waits: shared helper main+0x5ed3d0 (counter += category frames, category from the actor) used by
  ExecuteGenericWaitFrame (update main+0x26e7ef0), ...ByPlug (0x5ed4e0), SeqExecuteWaitFrame (0x3bb0be0),
  ExecuteWaitFrameOrInput (0x2888510); SeqExecuteGenericWaitFrame (0x32c0670) adds [[main+0x4e94b20]]+0x10 (same
  layout as the manager); ...WithStepRate (0x26e7d20) adds its StepRate parameter via main+0x3b4e220;
  ExecuteStartVoice update (main+0x2863200): timer +0x64 += category frames, done when > param + 10 frames.
  Node vtables: slot 0 getName (adrp/add of the name string), slot 10 enter, slot 11 update.
- Not cleared, in order: (1) the Timeline/Demo runtime (.evtm; extension table at main+0x4c639c8: .evfc, .evtm,
  EventTrigger) was not located; the movie param "TimelineFileNameSyncMovie" is only parsed (main+0x5a9ff0,
  0x3ba14a0), so whether the intro's timeline follows the movie or its own clock is unknown. (2) main+0x32932b0
  (one caller main+0x17be90): `obj+0x265fc += (uint32)frames` (0 per update above 60 fps) and integer per-update
  counters at obj+0x284; a state machine (states <= 0xe, masks 0x2e80/0x5000, a [-1,1] value at +0x124 scaled to
  256), probably input/UI, not dialogue. (3) integer frame conversions at main+0xa682ec and 0x3403b0c (actor side).
  Rounding of the step (0.25 +- jitter) cannot produce a 4x speed-up, so the pacer is not the cause.

Tools (session scratchpad `i128/`, regenerate if gone): `main.img` = recomp/nso.py image of exefs/main; `text.dis`
from capstone (`.venv` has capstone, lief); `adis.py <addr> [n]`, `fn.py <addr>` (function around an address),
`xref.py <addr>..` (adrp+add sites), `tm.py` (field histogram of the time manager), `gobj.py <page> <imm>` (same for
any **global), `vt.py <fn>` / `vtab.py <vtable>` (reloc-aware vtable lookup; RTTI names are stripped, class names
come from getName strings only), `fnstr.py` (strings a function references).

Test plan (GPU back, Cal not playing). The replay script (7 A presses, frames 300 520 700 900 1100 1300 1500, each
`<frame> A 4`) was `scratchpad/newgame.txt`; recreate it with those lines if gone. From the title it reaches New
Game and the intro; frames are 60 Hz input frames (input.c runs on the world clock).
1. `NX2NAVI_FPS_LIMIT=60 NX2NAVI_AUDIO_DUMP=$OUT/a60.raw tools/lab-run newgame.txt 3000 intro-60` and the same with
   `NX2NAVI_FPS_LIMIT=240 ... intro-240` (and 120, to tell 2x from 4x). The dump is raw float32 stereo at the mixer's
   rate (audio_mixer.c:276); LAB_KEEP=1.
2. Compare the first 20 s: 100 ms RMS envelope per file, list onsets (RMS rising above 3x the floor); the movie's
   music is the time base, the voice onsets are the measure. Expected: 60 = reference; 240 early by ~4x if a
   per-update counter, ~2x at 120; equal everywhere = not a frame counter (look at audio/voice scheduling instead).
3. If early: `NX2NAVI_WATCH` on the suspects while the intro runs (the frame counter write at main+0x6e6cf8 is not
   it unless something reads +0xd50: watch the update object's +0xd50 for reads), and a dump of the Timeline
   player's state once it is found (start from the .evtm table's resource class, main+0x4c639c8 - 0x18 holds its
   vtable functions 0x260c0b0/0x260c0c0).

## #128 first lab pass (2026-11-09 12:30-12:45 UTC, GPU): the audio envelopes point the same way as Cal's report

Setup: `tools/lab-run newgame.txt <60*rate> intro-<rate> NX2NAVI_FPS_LIMIT=<rate> NX2NAVI_PROFILE_DIR=<empty dir>
NX2NAVI_AUDIO_DUMP=... NX2NAVI_TRACE=perf` at 60, 120 and 240 (the pacer held 60.0/120.0/240.0 fps, speed 1.000 in
every 120-present window after boot; the untimed script lines run on game ticks, so the 7 A presses landed at ticks
300..1500 at every rate, i.e. presents 1477/2834/4670 for the last one). Envelopes: `scratchpad/i128/cmp.py` (100 ms RMS, dB)
over the three `scratchpad/i128/out/a<rate>.raw` dumps (float32 stereo 48 kHz).
- **The script needs an empty profile.** On a copy of Cal's profile the same 7 presses load slot 1 (castle courtyard
  at present 3600); the earlier note "from the title it reaches New Game" held only for a profile without saves.
- Menu sounds at 7.0 and 10.5 s are identical at all three rates (presses at the same game time; a boot of 4.1 s to the
  first sound). From 15 s the intro plays: its loud music onsets are shared (the 42-43.5 s dip, the 44.0 s onset,
  the 62.5-65 s silence at 60 fps), so the movie's music keeps wall/game time, as Cal says.
- Between them the energy moves earlier with the rate: 240 fps is 3-8 dB louder than 60 at 22-32 s and 5-12 dB quieter at
  33-42 s, 120 fps sits between (louder than 60 at 22-30, equal at 33-36). The first non-menu onset is at 15.0 s at 120 and
  240 but 16.0-16.5 s at 60. Consistent with voice lines starting earlier at higher present rates while the music stays;
  the envelope alone cannot separate voice from music, so this is a direction, not a measure.
- Frame 3600 at 60 fps (60 s) is a black picture with 3 passes (movie fade or a video frame), so a dump-frame shot does
  not show the dialogue box; dialogue timing needs shot.req shots or a voice-channel dump instead.
- Not done: the counter deltas. `NX2NAVI_WATCH` (patch 0005) is a GPU-side watch (vk_memory.c `vk_watch`: it logs
  replay touches of a guest range), so it sees nothing of CPU counters; a CPU read is needed instead. The main image is at
  a fixed 0x7000000000 (`loaded main at` in run.log), and guest addresses are host addresses, so a sampler reading
  `/proc/<pid>/mem` at the three counters (time manager **[main+0x4c7e890] +0x10/+0x18, the update object's +0xd50/+0xd58
  once its pointer is known, main+0x32932b0's obj+0x265fc/+0x284) once per second during the intro, at 60 and 240, gives
  the per-second deltas without a rebuild. The ostep patch set (recomp/patches-v111.txt lines 27-28) only replaces the
  frames-per-update at main+0x6e6cc0/6e6cc4; the update's own frame counter at +0xd50 still gets +1 per update
  (ldadd at 0x6e6cf8), and +0xd58 += s8 (the patched fraction), so +0xd50 is the one counter in that function that
  runs with the present rate. Whether the Timeline/voice scheduler reads it (directly or via the accessor
  main+0x128c840) is the next question; no reader was found statically.
- Next: (1) a mixer-side per-voice onset log (audio_mixer.c, voices with sample format 2/6 are the voice/SE decodes;
  log the first render of each voice with wall and game time) to measure the voice offsets exactly; (2) the
  /proc/<pid>/mem counter sampler; (3) shot.req shots every second between 15 and 45 s at 60 and 240 for the dialogue box.
- lab-run: the process guard raced with a process exiting (`a[0]: unbound variable`, set -u); fixed to skip an empty cmdline.

Round 4 (2026-11-09 17:30-18:10 UTC, lab, live profile, `load-slot01.txt` frame 1500; `.lab/bush-r3-castle` draw lists reused,
`.lab/bush-r4-skipcards` (passes.txt + final.png kept), `bush-r4-field`/`bush-r4-far` (final.png + run.log only)):
- **The close-LOD leaf cards are not drawn at all at the near spot.** Every draw of the vegetation shaders in frame 1500
  is `inst 1`: prepass 0144 (depth-only, fs 1bea821e on the other pipes) has vs 5d33dc48 x1 count 111 (ib 0x596148b00,
  base_vtx 341), dbfce868 x2 count 10224 (ib 0x58a765a4a) and 528, and three count 3/36 draws; the shadow passes 0175/0182
  repeat the 111; the main pass 0210 draws the same three index buffers with vs 838ad0cd/fs f6c57a19 (111), vs 12fa7810/fs
  f84a6511 (10224) and fs 9eb91494 (528). The frame has no indirect draws and no instanced draw that uses these shaders.
- `NX2NAVI_SKIP_SHADERS=838ad0cd6a6448c2,5d33dc481e2771ac` (both card vertex shaders) changes nothing on the two topiaries
  (crop diff `scratchpad/bush/r4-top-ab.png`: only butterflies differ), so the 37-triangle draw is not the missing foliage
  either; what we see is only the 10224-index vine mesh. The fragment side (task 2: fs 099b152e = alpha >= c5[27].x
  with a NaN-guarded perspective uv, else kill; fs f6c57a19 has no discard) is therefore moot for #138.
- Cause moves upstream of the draw list: the game never submits the leaf geometry at 15-40 m. Next (task 3): the LOD or
  cull decision in the lifted actor code: find who selects the vine-only mesh (object around ib 0x596148b00 / 0x58a765a4a,
  the pass 0138 camera const block vs. a leafy frame), and whether the far foliage is the same object or an impostor.
- No leafy reference by replay: `input-20261108-131323.txt` now lands at the Zora river entrance at frame 2400 on both
  the 11-08 profile copy (`lab-profile-flicker`) and the round-1 copy (`scratchpad/bush/prof`), 77 s each. A leafy
  reference needs a fresh recording from Cal (Hyrule Field facing the castle trees, with `NX2NAVI_DUMP_REQ=1`).

## #128 second lab pass (2026-11-09 13:25-14:05 UTC, GPU): the narration slots run per present; no CPU reader of the per-present counters

Tools (patch 0022, `tools/counter-sample`, `tools/counter-watch.gdb`): `NX2NAVI_TRACE=counters` logs `counters: present N
t=<monotonic s>` every 60 presents and `counters: voice <slot> start: buf fmt ch Hz present t audio-frame` when a voice slot is
rendered after a gap. `tools/counter-sample run <interval> <out> tools/lab-run ...` samples the CPU counters through
`/proc/<pid>/mem` on the same clock; it must be an ancestor of the game (Yama ptrace_scope 1, no CAP_SYS_PTRACE; a stray
`nx2navi.new` of an earlier run broke the first attempt, so it only takes a descendant). The update object is found by
scanning the heap for the callback record `{typeinfo, this, main+0x6e6be0, 0}` the framework keeps in itself at +0x258
(main+0x3b59eac): `this` = 0x1373cd100 in every run; the time manager is `[[main+0x4c7e890]] = [main+0x4e94b20]` =
0x1373d9468 (the heap lies below main at 0x7000000000). Runs i128i/k-{60,240}, empty profile, `newgame.txt`.

| counter | per present at 60 | per present at 240 | reader |
|---|---|---|---|
| update +0xd50 int32 (ldadd) | 1.000 | 1.000 | none: gdb awatch through the intro (i128w3-240, presents 1..7381, 34 voice starts) fires only at the update's own ldadd (7428 hits, one per update) |
| update +0xd58 double (+= s8) | 1.000 | 0.250 | only the update function (awatch, two sites) |
| time manager +0x10 frames/update | 1.0000 | 0.2500 (0.31-0.78 during boot) | 91 static sites, all patched values |
| time manager +0x18 s/update | 0.01667 | 0.00417 | 25 sites |
| time manager +0x1c int rate | 60 | 240 (147-193 during boot) | none: rwatch through the intro (i128w-240, presents 1..7561) fires only at its writer main+0x3b4e300 |
| time manager +0x0 gameplay frames | 1.0000 | 0.2500 | 21 sites |

Voice starts (slot, game seconds since the first present; the narration lines are one PCM16 stream slot each, 4096 B chunks,
slots 20-28; slots 1-19 are the menu/music beds starting at the same game time at both rates: 2.0/2.2, 5.0/5.1, 8.7/8.8, 10.9/11.2 s):

| rate | narration slot starts (s) | intervals (s) |
|---|---|---|
| 60 | 14.5 22.9 31.9 43.7 48.2 56.8 63.5 | 8.4 9.0 11.8 4.5 8.6 6.7 |
| 240 | 13.1 17.5 20.8 24.0 25.1 27.3 28.8 31.8 34.3 | 4.4 3.3 3.2 1.1 2.2 1.5 3.0 2.5 |

So the sequence of lines runs 2.5-4x faster per wall second at 240 while every value the ostep patch produces is right and
no CPU code reads the two counters that still run per present. The scheduler of the narration lines is therefore not
driven by main's time manager fields or the update counter directly; the remaining candidates are (a) the movie/Timeline
player (.evtm runtime, not located), stepping its cursor once per update with a constant (its own 1/60 or a per-update
tick), (b) a counter inside the lifted actor/event code that counts updates with a literal rather than the manager
(the `obj+0x284 += 1` family at main+0x32932b0, not sampled: its object was not located), (c) a wait on the voice's own
playback that ends early because the voice was started with the next line's data (the 240 intervals 1.1-3.3 s are shorter
than the lines themselves, which supports a frame-counted wait rather than a playback wait). No fix proposed yet; the next
step is a gdb awatch on the voice start path: break on the audren voice start (the first `counters: voice` of a narration
slot comes from a guest StartVoice IPC) with a guest backtrace to the caller that decided the moment, then walk its
wait up to the counter it compares.

## #128 third lab pass (2026-11-09 17:30-18:15 UTC, GPU): the voice start is the sound thread's; the decider is one hop further

Tools: `tools/gdbwrap` (copied to the game dir as `nx2navi.gdbwrap`, `LAB_EXE=nx2navi.gdbwrap GDB_SCRIPT=...`; gdb is the
game's parent, so Yama allows it) and `tools/voice-watch.gdb` (hw `watch -l` on the server voice slots 20-22's `state`, set from
the first `update_voice`; on a change: host `bt`, which shows the lifted frames as `f_<guest addr>` since every guest call is
a host call, and `gwalk`, the guest fp chain from `kern_cpu()->x[29]`). Runs i128p3-240 and i128p3b-240 (empty profile,
`newgame.txt`, 240 fps). A watch hit stalls the game for seconds the first time (7.6 s at the slot-20 start), so the
first narration line's timing in such a run is void; later hits cost ~50 ms.

Every narration slot start (20, 21, 22, state 0 -> 1) comes from the same guest stack, on the game's audio thread
(host `thread_main` -> `rt_call` -> `f_700536eb00` thread entry): `f_7005367360` -> `f_7003482e50` -> `f_7000dd2680`
(a sead delegate-list walk: vtable +0x70 on each node, node 0x1ade36838) -> `f_70036d51d0` (a thread loop on an `ldarb`
run flag, waits an event, then `f_70036d52d0` once per audio frame; thread object 0x1ac6766f0) -> `f_7005430a20` ->
`f_70053ed360` -> `f_700537fd00` = svc 0x21 SendSyncRequest (RequestUpdate). So `f_70036d52d0` is nn::atk's sound-frame
process: it allocates the voice and sets its play state itself; the game thread only marks the StreamSound as started
(atk's BasicSound::StartPrepared sets a flag that the sound frame reads). The decider is therefore not on this stack.
The host bt is enough, the fp chain adds the saved callee registers (`x/80gx kern_cpu()->sp` in i128p3b-240 run.log).

Next hop: the StreamSound/BasicSound object of a narration line and a hw watch on its start flag, hit on the game
thread, whose bt is the decider. Ways to get the object: (a) from the buffer address the `counters: voice` line prints
(0x1ac7f3000 for slot 21), scan the guest heap at the watch hit for that value: the atk StreamSoundPlayer's wave buffers
hold it, and the player is embedded in the StreamSound; (b) statically from `f_70036d52d0`'s callees down to the voice
start, back to the sound-object loop and its flag read. Heap addresses are deterministic across runs (disable-randomization),
so the object found once serves a second run with the watch. Budget: 2 gdb runs (~3 min each) plus the static reading.

## #128 fourth lab pass (2026-11-09 18:25-19:25 UTC, GPU): the start is decided inside atk's per-frame update, no separate start command

Runs i128p4-240 (heap scan at the slot-21 start, `tools/voice-scan.gdb`, dump of the 174 MB heap mapping 0x1a302e000-0x1ade37000 in
`scratchpad/i128/scan/`), i128p4q-240 (`tools/voice-queue.gdb`), i128p4s-240 (`tools/voice-stream.gdb`); empty profile, `newgame.txt`,
240 fps. **No decider yet, no patch 0023.** Established:
- The sound thread's frame function main+0x36d52d0 pops three lock-free MPMC queues at `[[this]+0x1b8]+0x80000` + 0x340 / 0x3b0 /
  0x3e8 (each {cap, buf, head, tail}: pops main+0x36d7040 / 0x36d71f0 / 0x36e0f40, the item runs through main+0x11dd60), then
  RequestUpdate. Between the slot-20 and slot-21 starts the two tails were pushed 137 times (per update), all from atk's update
  main+0x36d14d0 -> 0x36d5920: 89 from the sound-update thread (f_7000dd2680 -> 0x5fe10 -> 0x5fe60 -> 0x415300 -> 0x415860) and 48
  from the game thread's actor tree (f_7000f28c30 -> 0x9467b0 -> 0x346c680 -> 0x2cabd0 -> 0x2cacc0 x4 -> 0x50b20 -> 0x5fe60 ->
  0x415300). There is no distinct "start this sound" push: the voice start is a side effect of the per-frame update.
- Heap at the slot-21 start: the buffer 0x1ac7f3000 sits in the guest audren voice params (0x1ac68bb90), in a stream ring object
  0x1ade21d58 (vtable main+0x4c1a598, four 0x1000 B buffers at +0x18..+0x30, one of a pool of 0x1d8 B objects from 0x1ade20e98) and
  is referenced from a table of 0x240 B stream-reader entries at 0x1ac784f20 + k*0x240 (vtables main+0x4c1a7e8 / 0x4c1a838; +0x20 ring,
  +0x30 open flag, +0x40 data handle, +0x58 size). Entry 0x1ac7855e0 served the music beds (voices 8-13) and then slot 21. All its
  writes (open at +0x30, ring refill at ring+0x18) come from atk's stream loader main+0x6cb2d0 / 0x6caf50 under the update
  main+0x36d1440 -> 0x36cadb0 -> 0x36cefd0, on either of the two update callers above; the first-frame stall of a watch hit is 7 s.
- So the per-sound "please start" state is set by game code before atk's update sees it, and atk's update (main+0x36d1440 and its
  sound list) reads it. Next: inside main+0x36d1440's descendants find the per-sound list walk and the state/flag read that leads
  to 0x36cadb0 (the stream player's prepare/start), take that flag's address at the slot-21 case (gdb breakpoint on the call
  into 0x36cadb0 with `x19`/`x20`), and hw-watch it in one more run: the writer is the game thread's StartSound caller, the decider.
