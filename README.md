# NX2navi on Arch, through Nix

A dev shell with NX2navi's whole Linux toolchain from nixpkgs, so nothing is installed with pacman, and nixGL so the
game gets a Vulkan driver built against the shell's own glibc. The game itself is built the way upstream documents
(`docs/building.md`, "Linux (in progress)"), only from inside this shell. Nix never sees the game files.

The flake lives here and is read directly: `nix develop ~/claude/nx2navi`, or through the `justfile` beside it
(`just --list`). Nothing is modified in the NX2navi checkout.

## GPU

- AMD or Intel (Mesa): the default. `nixVulkanIntel` wraps the game; despite the name it carries every Mesa Vulkan
  driver, RADV included. All of it comes from cache.nixos.org.
- NVIDIA: `NX2NAVI_NVIDIA=1 nix develop --impure ~/claude/nx2navi`. nixGL fetches the driver of the host's exact version
  and repackages it (a one-time build, redone after a driver update); then wrap the game with `nixVulkanNvidia`.

## How the build works

The repository's two build paths do not cover Linux and Ocarina together: `tools/build_game.py` builds on Linux but
writes the glue of the other game versions (Switch 1 memory pool, NVN 1), and the kit `tools/make_game.py` knows
Ocarina 1.1.1 but compiles only with MSYS2 on Windows. `build-linux.py` here runs the kit's own lift (with its two
bring-up fixes) and glue writer, then compiles and links with the Linux flags of `build_game.py` through Ninja, plus
dav1d (the Switch 2 movies) and `-fdeclspec` (the FidelityFX header). Nothing in the checkout changes.

## Game files

A `.nup` dump is unencrypted and needs no keys: `NX2NAVI_NUP=/path/game.nup just extract` unpacks it with
`tools/make_game.py` (its exefs and romfs steps, stopped before the Windows compile) into the same
`build/extracted/<ver>` tree `tools/extract.py` would write from an NSP/XCI and prod.keys. Every later step is the same.

## Build

Game version code: `v111` for the 1.1.1 update (`v121`, `v143` exist too). Allow 60 GB in the checkout.

```nu
cd ~/claude/nx2navi/NX2navi   # worktree of ~/claude/.bare/NX2navi.git (just worktree)
nix develop ~/claude/nx2navi

uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r tools/requirements.txt
uv venv --python 3.14 .venv-py314
uv pip install --python .venv-py314/bin/python -r tools/requirements-py314.txt

cp config.example.toml config.local.toml
# edit: base, updates, keys with POSIX paths to your own files

.venv/bin/python tools/build_hactool.py
.venv/bin/python -I tools/make_game.py --nup /path/game.nup --out build/extracted/v111 --until romfs --msys ~/claude/nx2navi/.msys-stub
.venv/bin/python tools/build_xlate.py
.venv/bin/python recomp/gen.py --exefs build/extracted/v111/exefs --out generated/v111 --patches recomp/patches-v111.txt
.venv-py314/bin/python tools/make_romfs_patches.py --version v111
.venv/bin/python tools/build_game.py --version v111
sh tools/fetch_refs.sh
.venv-py314/bin/python tools/prepare_shaders.py build/v111 --version v111
nixVulkanIntel build/v111/nx2navi
```

Guest optimisation level and compiler cache (`build-linux.py`, #132): the lifted game code builds at `-O1`;
`NX2NAVI_GUEST_OPT=2 just game` (and `NX2NAVI_GUEST_FLAGS=-march=znver3`) builds another level into its own
`obj/guest-<tag>/`, so switching only relinks. Measured 2026-11-09: `-O2` and `-O2 -march=znver3` change neither the
field's frame rate (39-42 fps in every variant) nor the guest threads' CPU per frame (55.0 / 55.0 / 54.9 ms), so the
default stays `-O1` and PGO was not built (`NOTES-perf-2026-11-09.md` "Guest optimisation level"). Every compile goes
through ccache (`.ccache/`, 40 GB limit): a second build of the same variant is all hits, 52 s against 342 s.

Runtime flags (#148): `NX2NAVI_RUNTIME_FLAGS="-O3 -march=znver3" just game` (`build-linux.py --runtime-flags`,
objects in `obj/runtime-<tag>`, `-flto=thin` also goes on the link line). Measured 2026-11-10: -O3/znver3 and ThinLTO
stay inside the run-to-run spread (40-43 fps); a third of the replay thread is libc and kernel (shadow-sync memcpy,
write-watch and submit ioctls). `tools/cpu-sampler.c` samples one thread without perf (`perf_event_open` is denied in
the container); `tools/cpu-sampler-report.py` symbolises. NOTES-perf "Runtime optimisation".

`--cpu v2` on `build_game.py` only for a CPU without AVX2. The shader preparation opens a window: run it in the desktop
session. The game binary finds `libSDL3.so.0` and the Vulkan loader through the shell's `LD_LIBRARY_PATH`, so start it
from the shell (a desktop entry can call `nix develop ~/claude/nx2navi --command nixVulkanIntel <path>/nx2navi`).

## RADV workaround

Mesa 26.2.6's RADV crashes (`libvulkan_radeon.so+0x19be92`, writing address 0x40) while the game builds pipelines
through `VK_EXT_graphics_pipeline_library`, on the RX 6900 XT, inside the container and on the host alike. The
justfile runs the shader preparation and the game with `RADV_DEBUG=nogpl`; the runtime then builds whole pipelines,
and the vertex and fragment variants compile at their first draw (stutter on the first visit to an area). Mesa 25.2.6
(`just mesa=stable ...`, nixpkgs stable through a second nixGL) crashes the same way, so it is not one release.
Because whole pipelines build slowly, the justfile sets `NX2NAVI_PIPE_SKIP=any` (was `strict`; Cal found `any` smoother, 2026-11-08): full-screen draws wait for
their pipeline instead of being skipped, which otherwise shows as a black game picture under a working overlay.

## Linux fixes outside the checkout (runtime-linux/)

Two gaps in upstream's Linux platform layer stop Ocarina at boot; `build-linux.py` compiles `runtime-linux/frames.c`
beside the runtime and renames upstream's versions with per-file `-D` flags, so the checkout stays untouched:

- `plat_frame_capture` is a stub on Linux, so the guest's first `setjmp` was fatal. `frames.c` walks the host
  stack with the C unwinder and resumes the lifted caller's frame (`-Dlongjmp=nx_frame_resume` in guest_setjmp.c).
- `plat_fiber_new` starts a fiber's function with the stack misaligned by 8 bytes; glibc's `pthread_create` then
  faults on an aligned SSE store. `frames.c` wraps upstream's constructor and shifts the first frame by one word.

## Translator patches and the worktree (black picture, NaN fog)

`tools/build_xlate.py` applies its 34 patches with `git apply` from `build/`. In a worktree whose `.gitignore` lists
`build/`, git treats that directory as part of the checkout and skips a patch that creates a new file
(`0021-prmt-byte-permute.patch`, the PRMT byte-permute instruction), printing "Skipped patch" and exiting 0. The
translator then builds without PRMT, 6,006 shaders carried "PrmtR is not implemented", and every shader using it
read stale registers: the volumetric fog light injection wrote NaN into its froxel volume, the fog history made it
permanent, and the fog composite turned the whole picture black at the first outdoor scene. The justfile's `xlate`
recipe sets `GIT_CEILING_DIRECTORIES` to the checkout so git does not look upward from `build/`; after a translator
change run `just xlate game shaders` (the shader cache keys include the translator id).

## Upstream bug: mesh-stage c0 table overflow

`runtime/vk_exec_draw.c` writes the mesh stage's 16-entry storage table at 0x770 of a 0x800-byte stack bank, 112
bytes past its end, which in this build zeroes the caller's exec pointer: a deterministic crash at the first
mesh-shader scene (`upstream-issue-c0-mesh.md`, with the gdb backtrace and disassembly). `NX2NAVI_FIX_C0=0` (the
bank left zero) passes the spot, replaying `build/v111/logs/input-20261108-032149.txt`, but the game picture is black
with it: the shaders need those constants. The private patch 0006 clamps the table to the bank (9 rows for the mesh stage); before it, `build-linux.py`
compiled `vk_exec_draw.c` at `-O0` so the 112 bytes landed on a dead structure, at a CPU cost in the draw recorder.

Container replays are not representative past that point: Podman's default seccomp profile denies `userfaultfd`, the
runtime logs "no asynchronous userfaultfd write protection" and copies whole pools to the GPU every frame (1.4 fps,
black picture, an ASTC decode storm). `--cap-add SYS_PTRACE` on the container would let it through (not added yet:
Cal's decision, it widens the sandbox); on the host the write watch works ("0 untracked" in the logs).

## Obsolete stopgaps

The sky-SH NaN root cause is fixed by patch 0004 (build f33ed65). These stopgaps are obsolete and should not be run on
a new cache: `just nanguard` with `tools/nan-guard.py`, `tools/cas-nan-guard.py` and `tools/cas-reset.py`. They stay
only so `just nanguard restore` (and each tool's `.orig` restore) can undo what they wrote into the current cache.

## Status

2026-11-09 (morning). The game is played daily on the host (`just play`): Cal's save is in Hyrule Castle / Hyrule
Field, HDR10 native through niri-spicy, 240 Hz panel. Since the 2026-11-08 morning build:

- Lighting fixed at the source: the shadow sync skipped the CPU's per-frame zeroing of the sky-SH block, so the GPU
  kept adding into stale (or NaN) sums (patch 0004, build f33ed65). The pow NaN stopgaps are obsolete; `fmzpow` is still
  run until a fresh-cache test proves it unneeded (NOTES "fmz-pow after f33ed65").
- Performance 52 -> 64 fps in the haze replay: changed-page write-back (0001), the page compare outside shadow_lock
  (0008), compact freshness arrays (0009), neighbouring-pool queries (0010), async replay and recorder thread on by
  default. Heavy field scenes still drop to 36-46 fps under VRAM pressure (#132): the released-texture list holds
  7-8 GiB of render targets while small textures are evicted and re-uploaded (NOTES "VRAM pressure"). Patch 0019's
  byte cap is the `just play` default since 2026-11-09 (`NX2NAVI_TEX_RELEASED_MIB=3072`): in the lab replay of the
  19:58 play recording to frame 5000, VRAM stays at 12.8 GiB instead of 17.6 of 16.4 GiB, pressure drops 761 -> 0,
  59.6 vs 58.0 fps mean and p99 18.6 vs 27.6 ms over frames 3000-4000, no texture artefacts in 9 shots.
  Cal's real-play Tracy trace of 2026-11-09 (`NOTES-perf-2026-11-09.md`): Hyrule Field is a flat 22.9 ms (43 fps) with
  no spikes; the game's render thread is the critical path (the replay thread never blocks a present), 5.1 ms of it is
  `submit finish wait`, which includes the completion thread's 5.4 ms/frame of write-back compares because `done` is
  published after the callbacks; 17.8 ms of that thread is unzoned. Ranked fixes and new zones in the notes.
- #132 fixes 1 and 2 (2026-11-09 evening, patches 0024 and 0025, in `nx2navi.new`, not swapped): the submit finish wait
  and the LOD guard wait for the GPU alone (`reached_gpu`), and the write-back compare runs on 4 threads when a
  submission's list is 4 MiB or more. Lab A/B on the 19:58 field recording, 30 s of wall time after the area load,
  `NX2NAVI_FPS_LIMIT=240`, same binary with both toggles off vs on: 59.3 -> 60.4 fps mean, p99 29.6 -> 29.3 ms (an
  earlier pair 59.8 vs 58.7 with fix 1 alone; run-to-run noise is about 1 fps, and the replay diverges by wall time so
  windows are matched on the load spike, not on frame numbers). The lab scene compares only 6 MiB per frame (Cal's
  trace: 66), so the gain the notes predict needs his play to show; the first version of fix 2 without the threshold
  lost 5 fps in the lab to pool wakeups on 0.1 MiB lists. Castle slot (frame 1500) and crash spot (frame 1700) pass.
- #132 texture dedupe and released-list LRU (2026-11-09, patch 0028, in `nx2navi.new3`, not swapped, **both off by
  default**): the tex trace answers the Kakariko question of `NOTES-perf-2026-11-09.md`: first-time uploads are real
  new keys, not cache misses. Lab replay of the 17:47 recording to present 9000 (toggles off): 2516 MiB first-time, of
  which only 37 MiB are bytes uploaded before under another key (21 MiB address, 16 MiB descriptor; their entry mostly
  still live); castle slot: 9.5 of 2047 MiB. Dedupe shared 12 MiB (17:47) and 3.7 MiB (castle), every share verified,
  0 hash collisions, and it paints wrong terrain: large dark ground patches at the castle slot, frame 1500, with
  dedupe alone (`dd-castle-dd`) and with both toggles, clean with both off on the same binary. No fps gain (17:47
  replay, two 60 s windows: 80.9 / 57.2 fps off, 76.9 / 55.6 on; castle 27.1 either way). The cost that is left is the
  byte cap's churn: 2609 released-bytes sweeps (9.5 GiB) and 759 MiB of re-uploads in that replay; LRU did not lower it
  (924 MiB) and LRU alone has no lab shot yet (the lab was paused for Cal's play), so it is off until tested. Crash
  spot (frame 1700) passes.
- Debug and play features: shader hot-reload and on-request shots (0003), dump.req (0011), mark this moment (0015,
  F9 / L3+R3), draw lists in dumps (0017), Steam Input pad preferred (0014), projection unjitter (0012).
- Defaults: `NX2NAVI_PIPE_SKIP=any`, `NX2NAVI_HDR=native`, `REPLAY_ASYNC=1`, `VK_RECORDER=1`, `TEX_RELEASED_MIB=3072`.
- AO (#146): the occlusion trails one frame behind what moves (it runs before the frame's depth pass). `NX2NAVI_AO_ORDER=1`
  (patch 0046, off until Cal has played with it) runs it again after its event; `NX2NAVI_AO=0` (0045) turns it off.
  Event waits v3 (0016) stays off: it darkens the picture (castle slot, lab).
- Horizon bands (2026-11-09, open): thin vertical lines every 80 px over the hazy mid-distance field (Cal's shot-21152, binary through 0026); not reproduced in the lab yet, no toggle tested; NOTES "Horizon bands" has the candidates and the next replay.
- Open: #128 intro speed (second lab pass 2026-11-09: the narration voice slots start 2.5-4x faster per wall second at 240 than at 60 while the time manager and the update's +0xd58 step are patched correctly; the update's +0xd50 counter runs per present; the consumer is still unknown; third pass: the slots are started by atk's sound thread itself; fourth pass: no separate start command, the start is a side effect of atk's per-frame update main+0x36d1440 (two callers), stream reader entries and ring objects located, NOTES "#128 fourth lab pass"; tools/voice-{watch,scan,queue,stream}.gdb, tools/gdbwrap), #138 gray close-LOD bushes (cleared so far: mesh path, alpha test, render
  conditions, vertex formats (0018), occlusion-query culls (0020's `NX2NAVI_OQ_FORCE`), the shared vs c6 block; the vertex
  textures' data (round 3: the 512x512 rgba16f one is a live ping-ponged push/bend field written by compute every other
  frame); round 4: the leaf cards are not drawn at all at the near spot (every vegetation draw is inst 1, skipping the card vertex shaders changes nothing), so the cause is the game's LOD/cull decision before the draw list; next: the lifted actor code's LOD selection, NOTES "Gray close-LOD bushes" round 4), AO flicker (above), the mesh-stage c0 overflow upstream (worked around by 0006).
- Flatpak build kit for the Steam Deck (`flatpak/`, private CI artifact), untested on a Deck.
- The 2026-11-09 00:00 device losses (every lab replay, stock binary too) were a degraded amdgpu; a host reboot
  cleared them, replays pass again since the morning. `nx2navi` is the 00:28 build (patches through 0019);
  `nx2navi.prev` is the 22:14 build (through 0015).

## What was verified

- Build: the whole pipeline in the Manager's container (lift 297,414 functions, 318 MB binary), rebuilds of
  `nx2navi.new` from the `build` branch with `ninja -f build/v111/build.new.ninja`.
- Play on the host: hours of play across Kokiri Forest, the Deku Tree, Hyrule Field and the castle with pad, HDR10,
  60 fps outdoors (240 Hz panel, frame limit by the game), logs in `build/v111/logs/play-*.log`.
- Lab (container, RX 6900 XT through `/dev/dri` and the gpu-display compositor) until 2026-11-08 23:58: replays of
  Cal's recordings and slot save to fixed frames, with dumps, shots, core validation (two VUIDs, NOTES "Validation
  sweep") and A/B of patches 0004, 0008-0010, 0016. 2026-11-09 morning, after the reboot: the swapped-in build passes
  the castle spot (frame 1500) and the crash spot (frame 1700); `mark.req` during a replay logs `mark 1 at present
  832`, writes `logs/shot-00832.png` and, with `NX2NAVI_MARK_RING=1`, 30 frames in `logs/mark-1/`; 0019 A/B above.
- Not verified: the Flatpak kit on a Deck, fmz-pow's removal; 0018 is cleared as the #138 fix (no visible change).

## Private local patches

`patches/` holds local fixes to upstream NX2navi code. They are applied as local commits on the
`build` branch of the `NX2navi` worktree and are never pushed or published (the license forbids
distribution). After `just update`, `build` may need a rebase onto the new upstream.

- `0001-shadow-write-back-changed-pages.patch`: shadow write-back copies only pages the GPU changed
  (fixes the outdoor write-back storm, ~23 -> 30 fps).
- `0004-shadow-sync-next-part-writes.patch`: the shadow sync copies the CPU's bytes under the next part's own GPU
  writes (the game zeroes the sky-SH block on the CPU each frame; skipping that whitened the lighting outdoors).
- `0005-watch-range-log.patch`: `NX2NAVI_WATCH=<addr>:<size>` logs what touches a guest range (debug).
- `0006-vk_exec_draw-clamp-the-mesh-stage-s-c0-storage-table.patch`: the mesh stage's c0 storage table stops at the
  2 KiB bank (upstream-issue-c0-mesh.md), so `vk_exec_draw.c` builds at the normal `-O2` again instead of `-O0`.
- `0007-Screenshots-take-the-window-crop-the-present-shows-n.patch`: shot.req and NX2NAVI_SHOTS read the window
  crop, so a 1920x1080 crop in a 2560x1440 texture is no longer saved into the top-left of a black picture.
- `0008-vk_memory-compare-the-write-back-pages-outside-shado.patch`: the fence write-back's page compare (0001) runs
  before taking shadow_lock, so the render thread no longer waits on it (haze replay 51.9 -> 59.3 fps, p99 22.7 -> 19.9 ms).
- `0009-vk_texture-the-pool-s-per-submit-freshness-check-rea.patch`: the texture pool's per-submit freshness check
  over every registered slot (~21k) reads compact per-slot arrays instead of the TexSlot records (haze 59.1 -> 60.0 fps,
  p99 19.6 -> 19.1 ms).
- `0010-vk_memory-the-shadow-sync-queries-neighbouring-pools.patch`: the shadow sync sorts the touched pools and queries
  neighbouring ones (up to 64 KiB apart) in one write-watch query: 300 -> 197 queries and 2.27 -> 2.10 ms per frame;
  fps within noise (60.0 -> 60.1).
- `0011-vk_dump-NX2NAVI_DUMP_REQ-1-dumps-the-frame-after-a-d.patch`: `NX2NAVI_DUMP_REQ=1`: touching `dump.req` beside the
  shader cache dumps the next frame of a running game into `<dump dir>/f<frame>` (debug, repeatable).
- `0012-vk_usnap-zero-the-game-s-projection-jitter-when-no-t.patch`: distant shimmer. The game jitters its projection
  (scene context block 0x3500, rows 7-8 column 2) for its tensor-core temporal upscaler, which runs here as a plain
  scale (stand-in), so nothing resolves the jitter. `NX2NAVI_UNJITTER=auto|0|1|log` zeroes the two terms in the uniform
  snapshot; auto when no DLSS/FSR 3.1 runs. Proper route (not built): open-source FSR 2.x (FidelityFX SDK, Vulkan
  backend, builds on Linux) behind the same `vk_ffx` inputs, with the game's jitter fed to it instead of zeroed.
- `0013-nvn-order-cross-queue-WaitEvent-in-the-replay-NX2NAV.patch`: AO lag and flicker (experimental, **off by
  default**). The AO compute (cs 561cf523: 960x540 r8 from the half-res r32f depth, then an H+V blur, no history or
  noise) waits on an `nvnCommandBufferWaitEvent` that the frame's last submission (queue 134133020) signals after it
  writes the half-res depth. The replay ignored WaitEvent, so AO read the previous frame's depth. Proven live: AO forced
  to 1 removes the flicker; REPLAY_ASYNC=0 changes nothing. `NX2NAVI_EVENT_WAITS=1|log` cuts a submission at such a
  wait and holds the rest until the signal is issued (3 cuts a frame, all released on their signal), but the frame then
  flickers full screen. Cause not found yet: suspects are queue-carried state across the cut (`OP_EXEC_STATE`), or
  CPU-side ordering (uniform snapshots, mirrors, game polling event values). Next: a dump with it on vs off.

- `0016-nvn-event-waits-v3-wait-on-the-cut-s-own-event-cut-t.patch`: event waits v3 (still **off**). v2's held parts were
  released in the same submit call (ew_drain looked for a wait *after* the cut), so v2 only split submissions and AO
  still read last frame's depth. v3 holds until the cut's own event is signalled, cuts the signalling submission right after
  its signal so the released queues run before the rest of it, keeps the uniform snapshot across a cut, and returns a
  split submission's last fence. Lab (input-20261108-131323, frames 1100-1290): AO now reads this frame's half-res depth
  (passes.txt order), and brightness dips fell from ~15 to 0-1 per 190 frames (off: 0). Not default: one dip remains, and
  at the Hyrule Field castle spot (lab-profile-flicker) a waits=1 replay lost the device (`upload submit failed (-4)`).
  `NX2NAVI_EVENT_WAITS=trace` logs every submission's event ops and queue syncs.

- `0014-input-prefer-Steam-Input-s-virtual-pad-at-once-and-i.patch`: a "Steam Virtual Gamepad" or "Steam Deck
  Controller" (Steam Input) becomes the game's pad as soon as it is open, and the raw "Steam Controller" beside it is
  never followed on a press while the virtual pad exists. Other pads still take over on their first press.
- `0015-Mark-this-moment-F9-an-L3-R3-hold-or-mark.req-log-a-.patch`: mark this moment (#133), see below.

- `0017-vk_dump-NX2NAVI_DUMP_DRAWS-1-lists-every-draw-of-a-p.patch`: `NX2NAVI_DUMP_DRAWS=1` lists every draw of a pass in
  the dump's passes.txt (pipe, shaders, kind, count, instances, base vertex/instance, index or argument buffer), so two
  frames' draw lists can be diffed (`tools/dump-draws` summarises or diffs them).
- `0019-vk_texture-NX2NAVI_TEX_RELEASED_MIB-caps-the-own-mem.patch`: `NX2NAVI_TEX_RELEASED_MIB=<n>` (default 0 = off) caps the
  VRAM held by released textures kept for take-back (RELEASED_MAX 2048 entries, 7-8 GiB of render targets in the heavy field
  scene), dropping the oldest past the cap. `just play` sets 3072 since 2026-11-09 (Status has the lab numbers) (#132).
- `0022-NX2NAVI_TRACE-counters-a-present-clock-line-per-60-p.patch`: #128 lab instrumentation. `NX2NAVI_TRACE=counters`
  logs `counters: present N t=<CLOCK_MONOTONIC s>` every 60 presents (perf.c) and `counters: voice <slot> start: ...
  present N t=... audio-frame A` when a voice slot is rendered after a gap (audio_mixer.c). `tools/counter-sample run
  <interval> <out> tools/lab-run ...` reads the CPU counters of that game through `/proc/<pid>/mem` on the same clock
  (the update object's +0xd50/+0xd58 found through the callback record, the time manager through its pointer chain).
  Built into `nx2navi.new` (not swapped).
- `0023-Tracy-profiler-zones-rt_tracy.h-opt-in-with-build-li.patch`: #137 tooling for #132. `runtime/rt_tracy.h` wraps the
  Tracy C API (`RT_ZONE`, `RT_FRAME_MARK`, ...; every macro empty without `TRACY_ENABLE`) and zones sit where perf.c
  already times: the present (frame mark), `nvn submit` and `submit finish wait` (nvnQueueSubmitCommands), `shadow sync`,
  `write-back compare` and `write-back` (0008 area), `bind pipeline`, `texture upload` (text `re-upload`), `released
  sweep` (0019), `audio mix`. Built only by `just game tracy=1` (see "Profiling with Tracy"); the plain binary is untouched.
- `0024-vk_sync-the-submit-finish-wait-and-the-LOD-guard-wai.patch`: #132 fix 1 (NOTES-perf-2026-11-09 item 1). The
  completion thread publishes `reached_gpu` as soon as the timeline says the GPU is through with a value, before it
  runs that value's callbacks (write-back compares, pool resets, frees); `done` stays after them. The game thread's
  `submit finish wait` and the LOD guard wait on `reached_gpu` (`GfxBackend.gpu_wait`/`gpu_done`): both only order the
  GPU's reads of guest memory before the game rewrites it. Everything that reads what the GPU wrote (nvnSyncWait,
  Finish, texture and guest reads, usnap, pipeline-set waits) stays on `done`, which still follows the shadow
  write-back. `NX2NAVI_GPU_WAIT=0` restores the old wait. The patch message has the reasoning per waiter.
- `0025-vk_memory-the-write-back-compare-runs-on-a-small-thr.patch`: #132 fix 2 (item 2). `vk_gpu_written_many` takes a
  submission's whole written-range list from the draw recorder's completion callback, lays the ranges with a shadow end
  to end and splits that span into page-aligned slices over a persistent pool (`vk wb diff k` threads, started once);
  the changed runs are merged in worker order, so the copies under shadow_lock land as the sequential path's did.
  `NX2NAVI_DIFF_THREADS=n` (default 4, 1 = the old loop). Lab numbers: see Status.
- `0020-vk_exec_xfer-NX2NAVI_OQ_FORCE-forces-every-samples-p.patch`: debugging the game's CPU-side occlusion culls (#138):
  `NX2NAVI_LOG_OQ=1` logs every samples-passed report (address, queries, sum, count), `NX2NAVI_OQ_FORCE=<n>` makes each
  report write n (0 = off). Built into `nx2navi.new` (not swapped). A/B at the castle: forced counts do not restore the leaves.
- `0018-vk_pipeline-map-the-RGBX-sRGB-and-BGRX-vertex-format.patch`: vertex-format correctness fix (A/B cleared as the #138 bush cause).
  A vertex attribute whose NVN format had no table entry (RGBX8/16/32, 8-bit sRGB, BGRX8) read the zero binding
  (0, 0, 0, 1) silently, collapsing any shape with such an attribute; they now read as the 4-component format, and an
  attribute still without a mapping is logged once (`vk_pipeline: vertex attribute ... without a vertex format`). The
  A/B 2026-11-09 at the castle courtyard (Cal's slot save, frame 1500): the topiary 15 m ahead is bare with and
  without the patch and neither log has a `without a vertex format` line, so this is **not** the #138 cause; kept as
  a correctness fix, in the swapped-in binary.
- `0026-vk_device-under-a-RenderDoc-capture-NX2NAVI_RDOC-VK_.patch`: #135. While `NX2NAVI_RDOC` is set (rdoc.c loaded
  RenderDoc) `VK_EXT_external_memory_host` is neither required nor enabled: RenderDoc hides it and shadow mode never
  imports host memory. Inert otherwise. See "RenderDoc".
- `0028-vk_texture-identical-texture-bytes-share-one-VkImage.patch` (two commits): #132. `NX2NAVI_TEX_DEDUPE=1`: a
  first-time upload whose storage bytes hash like a compatible entry's (same descriptor apart from the address,
  verified by a compare) shares that entry's VkImage and unshares before a write. `NX2NAVI_TEX_RELEASED_LRU=1`: the
  released list drops the least recently used entry first, not the oldest release. Both **default 0** (second commit):
  dedupe paints wrong terrain at the castle slot and finds under 1% to share; LRU alone is untested (Status has the
  numbers). Kept for the trace: `NX2NAVI_TRACE=tex` gets a third line per 600 frames (what other-key repeats differ in,
  whether their entry is live / released / gone, dedupe shares, collisions, unshares).
- `0030-vk_texture-address-generations-that-name-the-bucket-.patch`: #132 round 3, texture-pool entry refresh. Two
  switches, both **default 0** (no measurable gain): `NX2NAVI_TEX_STATE_GEN=1` makes an address generation name the
  state of its bucket (a 64-bit sum of one term per entry; a state seen before gets its generation back), so the
  release + take-back of a transient render target no longer hands ~400 slots a new token; `NX2NAVI_TEX_CHECK_SKIP=1`
  skips the per-submit check of slots whose texture never uploads. Lab, field standing window: refills 17.2k -> 13.7k
  slots per switch, entry refresh 2.66 -> 2.67 ms, 42.7 -> 43.1 fps (noise); the check skip is worth under 0.2 ms.
  Castle slot and crash spot pass with both on, picture clean. Kept for the trace: `NX2NAVI_TRACE=perf` logs two lines
  per 600 pool switches (refills, how many wrote nothing, and the refresh split into whole-table walk, dirty walks,
  refills, descriptor writes, freshness checks). NOTES-perf-2026-11-09 "Round 3".
- `0031-platform-linux-the-crash-report-names-what-the-threa.patch`: #141. `plat_crash_context` was a no-op on Linux; a
  fault now prints `[host] crash: the thread was building a graphics pipeline stage ...` (shader key prefixes) before
  the FATAL lines. Reason: the 2026-11-09 22:31 graveyard crash is a NULL write in `radv_shader_spirv_to_nir`
  (libvulkan_radeon.so+0x19be92, Mesa 26.2.6: `spirv_to_nir` returned NULL and RADV does not check), i.e. Mesa rejected
  a SPIR-V module of one pipeline build, and the log did not say which. Built into `nx2navi.crash` (not swapped).
- `0033-platform-plat_fault_guard-so-a-driver-fault-inside-v.patch`: #141 guard. The four `vkCreate*Pipelines` calls run
  under `plat_fault_guard` (Linux: sigsetjmp; a fault of that thread outside the executable jumps back): a module
  Mesa rejects now costs one pipeline (`vk_pipeline: the driver faulted building ... stage <key>: not built`, its draws
  are skipped) instead of the session. The call sites landed in 0032 by accident (two agents in `vk_pipeline.c`), with a
  `TESTHACK` line that 0033 removes, so 0032 does not build without 0033. Test: every 7th module truncated to its
  header gives the same fault (+0x19be92, address 0x40), 4 caught, replay to frame 1500 completes; castle (1500) and
  crash spot (1700) pass. Which module Mesa rejected on 2026-11-09 is still unknown: the next occurrence names it.
  Built into `nx2navi.crash` (not swapped).
- `0032-vk_pipeline-the-cache-save-is-skipped-when-the-drive.patch`: slow exit. The exit save rewrote the whole
  pipeline cache (4.3 GB: copy, write, fsync) even when the autosave had just written it: castle slot exit 24.5 s ->
  1.3 s (in-process 17 ms; the rest is process teardown). A save is skipped when the driver's data size is unchanged
  since the last load or write (the driver only adds). Logs `pipeline cache N MB loaded (read, driver import)`, slow
  saves, and `gfx: exit took N ms` per stage. Why 4.3 GB: `LAB_HANG=1` runs (RADV_DEBUG=hang keeps every shader's IR
  text) wrote 9184 entries, 4.0 GB, under keys normal runs never ask for; the rest is 120 MB. lab-run now gives hang
  runs a scratch cache and waits for the game to exit (killing it mid-save left 79 `pipeline-cache.bin.*.tmp`, ~36 GB).
  `tools/pipeline-cache-strip <in> <out>` writes a copy without those entries: load 4.6 s -> 0.6 s, working set
  4.7 -> 0.8 GB, no pipeline stalls on the castle replay.
- `0033-vk_exec_draw-NX2NAVI_ONESHOT_WAIT_MS-caps-how-long-a.patch`: `NX2NAVI_ONESHOT_WAIT_MS=<n>` (default 30000,
  unchanged) caps the wait of a draw into never-rendered targets for its pipeline. A fight frame waited 637.6 ms on
  one such graphics draw (54 vertices, fresh 960x540 targets) despite PIPE_SKIP=any. Low values skip it instead; a
  true one-shot would stay empty, so off by default and not yet lab-checked.
- `0035-NX2NAVI_TRACE-nvn-each-guest-thread-s-time-per-host-.patch`: #132 tooling. `NX2NAVI_TRACE=nvn` times every host
  function call and SVC (rdtsc, exclusive) per guest thread and logs every 600 presents, for the presenting thread and
  the six threads with the most guest code: guest code (the rest), host functions, SVCs, and the top entries (15 for
  the first thread). Thread handles match `NX2NAVI_TRACE=sched`. About 20 ns per call. Table: NOTES-perf "Round 3".
- `0036-vk_sync-NX2NAVI_FINISH_DEFER-1-ends-the-submit-finis.patch`: #132. `NX2NAVI_FINISH_DEFER=1` (**default 0**, async
  replay only): the submit finish wait returns once the submission is on the GPU; the replay thread waits for the GPU
  before the next submission's shadow sync. Castle slot and crash spot pass, picture clean; no gain (42.3 / 41.0 fps
  against 42.7 / 43.1 in the field window): the wait is for the replay thread, not the GPU.
- `0037-vk_memory-log-VRAM-per-heap-every-1800-frames.patch`: #141/#132. Every 1800 frames (600 with `NX2NAVI_TRACE=perf`)
  the `mem: vram frame` census plus `mem: heaps frame N:` per heap: the driver's VK_EXT_memory_budget usage/budget (what the
  pressure valves read), VMA blocks and allocations, the kernel's `/proc/self/fdinfo` drm-memory-vram/gtt and visible VRAM
  (what nvtop shows) and the shadow total. Logging only. Reason: the play log's only budget figures (`stays imported ...
  6961 of 7925 MiB`) are the first four refusals, in minute 1, so a 16 GB card fill was invisible in the log.
- `0038-vk_texture-texture-memory-by-format-in-the-heaps-log.patch`: #132. After the heaps line, `mem: textures frame N`: own
  texture memory grouped by Vulkan format, ASTC footprint, render target (`rt`) and released (`rel`), largest 16, with the
  guest storage bytes per group. Logging only. Lab, Death Mountain start (input-20261110-004353, frame 3600): driver, VMA and
  kernel agree (VRAM 11.5 / 11.1 / 11.6 GiB, GTT 5.6 with 4.85 shadow): no hidden memory; render targets 5.5 GiB (3.3 released),
  ASTC as BC3 2.0 GiB from 0.9 GiB of ASTC, mirrors 1.0 GiB.
- `0042-vk_texture-NX2NAVI_TEX_RELEASED_YIELD.patch`: #132/#141. `NX2NAVI_TEX_RELEASED_YIELD=<percent>` (**default 0**):
  every 8 submits, when the driver's device-local usage minus VMA's free space inside its blocks passes that share of the
  budget, the oldest released entries go, render targets included, down to 5 points below (at most 64 per query). The
  slack term matters: without it a drop never lowered the driver figure (VMA keeps part-empty blocks: allocations 10.8 ->
  7.7 GiB, blocks stayed 10.4) and the list was emptied every query, 4.6 GiB re-created per second. Lab, Death Mountain
  start, frame 3600 (standing): off 11.5 GiB driver VRAM, released 3.3 GiB; 60% -> 9.7 GiB, released 1.3 GiB, 55.0 vs 53.6
  fps, worst-frame texture upload 428 vs 775 ms (load); 70% never fires there (68.8%). Castle 1500 and crash spot 1700
  pass with 60%, picture clean. Proposed play default: 85.
- `0043-vk_exec_draw-format-the-dump-s-draw-arguments-only-i.patch`: #148 step 1. `DUMP_ARGS` (op_draw, op_draw_idx,
  indirect) ran snprintf on every draw whenever any `NX2NAVI_DUMP*` was set, as `tools/lab-run` always does; it now
  formats only in a frame being dumped (`vk_dump_active`). Plain fix, lab-only cost: the replay-thread profile loses its
  snprintf (1.5% -> 0); field window 41.1 -> 42.1, 42.7 fps, replay 20.6 -> 20.2, 20.1 ms (inside the spread).
- `0044-vk_memory-NX2NAVI_SHADOW_NT-and-NX2NAVI_SHADOW_GAP_K.patch`: #148 steps 3-4, both **default off**.
  `NX2NAVI_SHADOW_NT=1`: shadow copies of 4 KiB and more use AVX2 non-temporal stores, fenced before the submit;
  field window shadow sync 2.9 -> 2.0 ms/frame for the same 10.9 MiB, replay 20.1 -> 19.4 ms, 42.4 -> 43.6 fps, p99
  26.5 -> 25.5 ms (two runs each). `NX2NAVI_SHADOW_GAP_KIB=<n>` (default 64): touched pools up to n KiB apart share one
  write-watch query; 2048 cuts queries 232 -> 160 a frame but the sync only 0.05 ms. NOTES-perf "Replay thread".
- Guest memory and the missing-geometry holes (#141), all in `runtime/memory.c`, built into `nx2navi.crash` (not swapped):
  `0034-memory-log-SetHeapSize...`, `0035-memory-log-the-first-MapPhysicalMemory...`, `0040-memory-at-the-first-refused...`
  and `0041-memory-the-MapPhysicalMemory-high-water...` are log lines (`mem: SetHeapSize`, `mem: MapPhysicalMemory
  high-water`, `... succeeds N ms after the first of K refusals`, `mem: alias census at a refusal`).
  `0039-memory-NX2NAVI_ALIAS_EXTRA_MIB...`: `NX2NAVI_ALIAS_EXTRA_MIB=<n>` (**default 0**) lets MapPhysicalMemory map n MiB
  beyond the pool the game is told about; the reported total and the heap stay, the reported used size stops at the total.
  What the lab showed (replays of `input-20261109-234907.txt`): the game's HeapDef gives `VirtualAddressMemory` 2802 MiB
  and the heap is pool - images - that (6910 of 9809 MiB), so `NX2NAVI_APP_POOL=12 GiB` only grows the heap to 9388 MiB
  and refusals stay. A refusal (0x10801, LimitReached) is the game's evict-and-retry signal: every one is followed by a
  successful map within 3-10 ms after it unmapped 0-9 MiB. At the ceiling about 5400 mappings are live (3500 of
  64-256 KiB, 12 above 16 MiB holding 840 MiB). To frame 16000: 71 refusals at the default, 0 with 2048 or 512 MiB
  extra, where the alias peak settles near 2990 MiB (185 MiB past the pool) from frame 5400 on. Not shown: that the
  holes Cal marked go away (replays drift), and why the console would not hit the same limit. Try in play:
  `NX2NAVI_EXE=crash NX2NAVI_ALIAS_EXTRA_MIB=512 just play`.

- `0045-vk_exec_draw-NX2NAVI_AO-0-turns-the-ambient-occlusio.patch`: #146 fallback. `NX2NAVI_AO=0` (default 1) overwrites the
  occlusion compute's result (cs 561cf523) with 1 right after its dispatch, so the blurs and the lighting resolve see no
  occlusion. Lab: the blur outputs are a flat 1; the picture loses the soft darkening in creases and under objects,
  0.1% brighter at the castle slot and about 2-3% at the graveyard gate (480x270 region means, one run each).
- `0046-vk_exec-NX2NAVI_AO_ORDER-1-runs-the-ambient-occlusio.patch`: #146, the targeted reorder (**default 0** until Cal
  has played with it). The replay notes each unmet WaitEvent with the queue state there; at the matching SignalEvent
  of the frame's main submission it replays the binds and the three occlusion shaders (561cf523, blurs cd6ddba0 and
  8b563e79) recorded after the wait once more, in the same command buffer, and goes on. No submission is cut or held
  (0013/0016 did that), fences are untouched, the early run stays. Asynchronous replay only. Lab (`nx2navi.ao`): the
  occlusion reads this frame's half-res depth in 300 of 300 frames (before: 0); in a slow pan (1-2 half-res px per
  frame) the early and the late occlusion image of one frame differ by more than 6% in 2.5% of the pixels; standing
  still at the castle slot and the graveyard gate: 0 brightness outliers in 300 frames with it off and on, sharpness
  92.6 vs 93.9 (Laplacian variance, 200 full-size frames), 28.4 vs 28.2 fps and 33.2-33.8 vs 33.1-33.4 fps; crash spot
  (frame 1700) passes. Event waits v3 at the same castle spot: the region 23% darker and 5 dark frames in 300, which
  is the side effect Cal saw. NOTES "AO flicker (#146)".
- `0047-vk_exec_draw-NX2NAVI_AO_TRACE-1-logs-the-ambient-occ.patch`: `NX2NAVI_AO_TRACE=1` logs `ao: f<frame> fence <n>
  depth|occlusion|blur|mask` lines with the bound images in replay order. The logging slows the replay (28 -> 22 fps)
  and runs with it showed single-frame bright, hazy flashes that runs without it did not: debug only.
- `0048-vk_exec_draw-NX2NAVI_POOL_KH-1-keeps-each-texture-sl.patch`: #132, `NX2NAVI_POOL_KH=1` (**default 0**) keeps each
  texture slot's descriptor hash in a dense array beside the registration it came from, so a bindless pool refill whose
  token moved only by its address generation skips the read of the slot's texture-table record (`pool_fill` ->
  `vk_texture_slot_khash_locked`, 3.7% of the replay thread, a cache miss per refill). Lab field window (`nx2navi.bind`,
  same binary): replay 20.29/19.96 -> 19.54/19.71/19.76 ms, 41.7/42.5 -> 43.2/42.9/42.8 fps, p99 unchanged; inside the
  run spread, indicative. Castle 1500 and crash 1700 shots match knob off. NOTES-perf "Binding caches".
- `0049-boot-NX2NAVI_MARK_RING-n-and-NX2NAVI_MARK_BURST-n-wr.patch`: #156, `NX2NAVI_MARK_RING=<n>` / `NX2NAVI_MARK_BURST=<n>`
  (**default 0**, RING=1 as before): a mark writes the n thumbnails before / after it to `logs/burst-<present>/`, see
  "Mark this moment". Built and unit-checked off the GPU (synthetic frame: stats 0.09 ms + PNG 1.19 ms per 320x180
  frame on the writer thread); first real run is Cal's next session. Binary `nx2navi.burst`.
- `0050-xlate-txq-layer-count-2d-array.patch` (translator, applied only by `tools/build-xlate-private.py` like 0002; not
  in the play build yet) and `tools/txq-array-fix.py` (the same fix as a post-pass on cached SPIR-V): #161, the
  2026-11-10 pipeline faults (`fault caught at libvulkan_radeon.so+0x19be92, address 0x40`, 17 in one session, each a
  mesh that is never drawn). The rejected module is the one that reads the layer count (TXQ .z) of a texture the
  translator knows only as plain 2D (res.json note "无 PC 类型，按 2D"): it emits `OpCompositeExtract ... 2` on the
  ivec2 of `OpImageQuerySizeLod`, `spirv-val` says "Vector access is out of bounds", Mesa's spirv_to_nir returns NULL
  and RADV dereferences it. 16 of the 17 are the vertex shader (the fragment named in the log is innocent), one is
  fragment 25d7025a. The fragment partners sample the same handle as a 2D array, so the fix types it as one: the
  translator patch does it at the size query (the res.json type becomes 259, the runtime then binds an array view);
  the post-pass retypes the variable and the query in place and refuses a texture used for anything else.
  `tools/txq-array-fix.py --cache <shader-cache> <backup dir>` rewrites a whole cache (backup, temp + rename): 222 of
  132,449 modules in the 2026-11-10 cache are affected. Post-pass files keep res.json type 3, so the view stays 2D
  and the layer count likely reads 1 (an animation that picks a layer would stay on the first) until a retranslation
  with 0050. State: 17 rewritten live through the reload loop (originals in `build/v111/reload-bak/`), all
  `spirv-val` clean; none was drawn again before the report, so a successful pipeline build is **not yet seen**.
  0050 compiles (scratch build `.lab/xlate-txq/build`) but has not translated an affected shader.

## Mark this moment

When a glitch shows, mark it with one of: **F9** (game window focused), **L3+R3 held 0.5 s** (both stick clicks;
hidden from the game while both are down), or `touch build/v111/mark.req` from any tool. Each mark:

- logs `mark N at present P (why)` in the play log;
- saves that present as `logs/shot-<P>.png` (also on HDR10: native HDR's PQ picture is decoded to sRGB);
- touches `dump.req` when the game runs with `NX2NAVI_DUMP_REQ=1`, so the next frame is dumped;
- with `NX2NAVI_MARK_RING=1`, writes the last 30 presents as 320x180 PNGs to `logs/mark-<N>/` (a GPU blit per present
  into a 7 MB host-visible ring, the flight recorder's; written on a background thread). Off by default.
- with `NX2NAVI_MARK_RING=<n>` (n >= 2) the last n presents and with `NX2NAVI_MARK_BURST=<n>` the next n, both to
  `logs/burst-<P>/<frame>.png` (320x180, the same GPU ring sized max(n) + 16 slots, about 0.23 MB per slot), plus a
  log line per frame `mark N: frame F luma L black B white W`. Suggested: `NX2NAVI_MARK_RING=120 NX2NAVI_MARK_BURST=120`
  (2 s each side, about 55 MB per mark on disk). A background thread copies the frames into memory as the ring holds
  them, then writes the PNGs (about 1.3 ms CPU per frame there); the present path pays only the blit. Both off by default.
  `tools/burst-scan logs/burst-<P>` lists frames that differ from both neighbours while those agree (a one-frame blank,
  flash or missing object) and writes `scan.png` (previous / frame / next per suspect). Patch 0049, #156.

Settings: `NX2NAVI_MARK_CHORD` (pad buttons joined by `+`: south east west north lstick rstick l r zl zr start back
dpad_*; `off` for none; default `lstick+rstick`), `NX2NAVI_MARK_HOLD_MS` (500).

yakin quick-menu item (add it to the `[menu] items` of your yakin config yourself), for a mark without the chord:

```toml
{ label = "Mark glitch", icon = "screenshot", target = "desktop:spawn:touch /home/purplg/claude/nx2navi/NX2navi/build/v111/mark.req" },
```

## Motion from a second gamepad (patch 0034)

`NX2NAVI_MOTION_PAD` (default `auto`, restart): when the gamepad in use has no gyro and accelerometer, the first other
open gamepad with both feeds the six-axis sensor, e.g. yakin's virtual "Xbox 360 Controller" (uinput, no sensors)
beside the kernel hid-steam "Steam Controller". Log: `input: motion from "Steam Controller" (buttons from "Xbox 360
Controller")`. That pad's buttons, sticks and rumble stay ignored and it is never made the pad in use (auto: the raw
"Steam Controller" beside another pad). `off` keeps only the in-use pad's sensors; any other text forces the first pad
with sensors whose name contains it. `NX2NAVI_MOTION=0` still turns motion off. SDL passes evdev sensor axes through
unchanged, so `input_motion_axes` holds if hid-steam reports in SDL's convention like hid-playstation; not checked on
the hardware. Probe: `--probe-cfg` (motion pad checks). Castle-recording replay (frame 1500) unchanged.

## Recording bundles

`just play` copies the profile's `save`, `save-tx` and `save-backup` into `build/v111/logs/profile-<ts>/` before the
game starts, with the same `<ts>` as its `input-<ts>.txt`, so a recording keeps the save it started from (the newest 40
bundles are kept). `tools/lab-run` given such a recording and no `NX2NAVI_PROFILE_DIR` builds a scratch profile in
`.lab/<label>/profile` (a copy of the live profile with the bundle's save dirs) and replays from it, so old recordings
replay exactly. Without a bundle it warns and falls back to the live profile, saves snapshotted and restored.
`lab-run --dry <rec> 0 <label>` only assembles and lists the profile.

## Scenarios (regression checks)

`scenarios/` keeps Cal's saves and recordings for the standard checks (castle 1500, crash spot 1700, graveyard gate,
field standing window) and the starting points of open bugs (#138, #141, #146, #149, #150, Kakariko, combat hitch),
8 MB in all. `just regress` replays the regression-grade ones through `tools/lab-run` on scratch profiles and a
pipeline cache copy, waits while Cal plays, and writes `.lab/regress/<time>.json`; `NX2NAVI_EXE=next just regress`
judges a variant before he plays it. `scenarios/README.md` has the schema and `just scenario-add`.

## lab-run debug options

Both are opt-in environment variables for `tools/lab-run` (see its header):

- `LAB_VALIDATE=1`: Khronos validation layer from nixpkgs plus synchronization validation. Messages go to `.lab/<label>/validation.log`, at most 3 per message ID. Slow.
  `LAB_VALIDATE=core` drops synchronization validation. Known (2026-11-09): sync validation, and core checks together with
  `check_shaders`, stall the game at boot (every thread in a futex wait); lab-run leaves check_shaders off
  (`LAB_VALIDATE_SHADERS=true` turns it on), so only `LAB_VALIDATE=core` gets through. `LAB_VALIDATE_THREADS`, `LAB_VALIDATE_FGL`,
  `LAB_VALIDATE_SETTINGS="key=value;..."` help to bisect the layer; `LAB_EXE=nx2navi.new` replays another binary in the game dir.
- `LAB_HANG=1`: `RADV_DEBUG=nogpl,hang`; the `radv_dumps_*` hang reports land in `.lab/<label>/hang`. Known: replays to frame 1100 hit `radv: GPU hang detected`, then radv crashes
  (libvulkan_radeon.so+0xfae0c) before writing a report.

## Profiling with Tracy

Opt-in, patch 0023. `just game tracy=1` builds `build/v111/nx2navi.tracy` (`build-linux.py --tracy --exe nx2navi.tracy`:
runtime objects in `obj/runtime-tracy`, `-DTRACY_ENABLE`, linked to nixpkgs tracy's `libTracyClient.so`; the lifted
objects are shared with the plain build). The plain `nx2navi` has no Tracy code at all: the `RT_*` macros of
`runtime/rt_tracy.h` compile to nothing. The client listens on port 8086 from the first frame and keeps a ring of events
until a server connects; no `NX2NAVI_*` switch is needed. No GPU zones yet: TracyVk is C++ only and the Vulkan code is C.
Known: the prebuilt client installs its own crash handlers when a profiler connects and would abort on the guest's
first write-watch SIGSEGV (seen at frame ~1240 of the lab replay); `RT_TRACY_FRAME()` in perf_present puts the
runtime's handlers back for the 300 presents after each connection (`plat_fault_reinstall`).

On the host, Cal runs the profiler GUI and connects to the game's port, which the container must relay (Nushell):

```nu
tally port add 8086                      # once; host 127.0.0.1:8086 -> the container's 8086
nix shell nixpkgs#tracy -c tracy -a 127.0.0.1 -p 8086
```

A game started on the host (`just play`) is on the host's loopback already, no relay needed. Or capture to a file first
and open it later with `tracy <file>`:

```nu
nix shell nixpkgs#tracy -c tracy-capture -o run.tracy -a 127.0.0.1 -p 8086 -f
```

Lab recipe in the container (`-f` overwrites; capture starts first, retries until the game listens, and writes the file
when the game ends):

```sh
nix shell nixpkgs#tracy -c tracy-capture -o .lab/zones.tracy -a 127.0.0.1 -p 8086 -f &
LAB_EXE=nx2navi.tracy tools/lab-run NX2navi/build/v111/logs/input-20261108-213627.txt 1500 tracy-zones \
  NX2NAVI_REPLAY_ASYNC=1 NX2NAVI_VK_RECORDER=1 NX2NAVI_TEX_RELEASED_MIB=3072
nix shell nixpkgs#tracy -c tracy-csvexport .lab/zones.tracy | head     # zone statistics without the GUI
```

Zones: `nvn submit`, `submit finish wait`, `shadow sync`, `write-back compare`, `write-back`, `bind pipeline`,
`texture upload` (zone text `re-upload` for a re-upload, value = bytes), `released sweep`, `audio mix`; frames are marked
at the present. Overhead: see Status (2026-11-09, measured against `nx2navi.new` on the same replay).

`tracy-csvexport` does not export frame marks; `NOTES-perf-2026-11-09.md` "Method" has the 12-line addition to
`csvexport.cpp` (Tracy's `Worker::GetFrames`) that prints them. Zones to add next, from that analysis: `frame bound` /
`replay full` (the game's waits for the replay thread, `vk_backend.c`), `nvn block <name>` at the `NVN_BLOCKING()` entries,
`replay submit` / `part submit` (the replay thread's recording per submission and `vkQueueSubmit2` per part),
`completion cb` and `lod guard` (how much of a fence wait is callbacks).

## RenderDoc

Opt-in, #135: capture one frame once, then inspect it standalone in seconds, no game run, no drift. Two halves: the
capture (the game under RenderDoc's Vulkan layer, one `.rdc` per present) and the replay (`tools/rdc` without a GUI,
or `qrenderdoc` on the host). Upstream has the in-app hook already (`runtime/rdoc.c`: `NX2NAVI_RDOC=<frame>[,...]`
captures those presents, `NX2NAVI_RDOC_DIR`, `NX2NAVI_RDOC_DLL`; it loads `librenderdoc.so`, sets
AllowUnsupportedVendorExtensions, RefAllResources and SaveAllInitials and the file template). It needs the layer in the
loader too (`VK_ADD_IMPLICIT_LAYER_PATH` to nixpkgs renderdoc's `share/vulkan/implicit_layer.d`,
`ENABLE_VULKAN_RENDERDOC_CAPTURE=1`), and **patch 0026**: RenderDoc 1.47 does not know `VK_EXT_external_memory_host`,
which `vk_device.c` required, so device creation failed under the layer (upstream's `docs/controls.md` calls it
blocked); shadow mode, the Linux default, never imports host memory, so with `NX2NAVI_RDOC` set the extension is
neither required nor enabled. The capture of present N holds N's submits and its present. A frame dump
(`NX2NAVI_DUMP`) of the same frame would record its copies into the capture, so dump a later frame.

Lab (`tools/lab-run`): `LAB_RENDERDOC=<frame>[,<frame>...]`; the captures land in `.lab/<label>/nx2navi_capture*.rdc` (the
run log's `rdoc: frame N captured: <path>` maps them to presents). lab-run waits for that line before it stops the
game. Measured (castle, frame 1500, 2560x1440): 203 s to the capture, a 10.3 GB `.rdc` (RefAllResources and
SaveAllInitials are on in rdoc.c, and shadow mode's pools are full copies of guest memory); opening that capture for
replay takes 221 s (chunk initialisation, CPU-bound), then every query is quick. `LAB_VALIDATE` stacks on top (the
validation layer outside RenderDoc's). Castle spot, frame 1500, with the binary built from patch 0026 (`--exe
nx2navi.rdoc --rt-obj runtime-rdoc`, so its runtime objects never race the plain build's):

```sh
LAB_RENDERDOC=1500 LAB_EXE=nx2navi.rdoc tools/lab-run lab-profile-flicker/load-slot01.txt 1501 rdoc-castle \
  NX2NAVI_PROFILE_DIR=$HOME/claude/nx2navi/lab-profile-flicker
tools/rdc info .lab/rdoc-castle/nx2navi_capture.rdc
```

`tools/rdc` (nixpkgs renderdoc rebuilt with its Python module, `tools/rdc.nix`; the first call builds it, 20-40 min,
cached after; the replay runs on the GPU through the flake's `nixVulkanIntel` like lab-run, so not while Cal plays,
and it holds lab-run's lock `/tmp/nx2navi-lab.lock` for its run: one GPU job at a time, a replay beside a lab run
ended that run in `VK_ERROR_DEVICE_LOST` on 2026-11-09. The Python module must not be preceded by a `RTLD_GLOBAL`
dlopen of `librenderdoc.so`: its exported layer entry points then shadow the loader's and the replay segfaults).
Known hazard (2026-11-09): replaying the 10 GB castle capture under VRAM pressure crashed the replayer itself (null
dereference inside `librenderdoc.so`, host dmesg) minutes before the device loss. Keep captures small (capture only
the present you need; a frame dump of a later frame, not the same one) and run `rdc` only with the lab lock held and
nothing else on the GPU:

- `tools/rdc info x.rdc`: frame number, draw/dispatch/pass counts, file sizes, every pipeline with its draw count,
  first event and shader hashes (sha1 of the SPIR-V, first 10 hex digits).
- `tools/rdc draws x.rdc`: one line per draw or dispatch: event id, pass, pipeline, vs/fs hashes, index and instance
  counts (dispatch size), viewport, depth test/write/function, blend per target and write mask, the bound targets with
  size and format.
- `tools/rdc save x.rdc <eventId> out.png [i|depth]`: colour target i (default 0) or the depth target as it is after
  that event.
- `tools/rdc shader x.rdc <eventId> vs|fs|cs|gs|ms|ts [target]`: disassembly; the default target is SPIR-V, a substring
  picks another one RenderDoc offers (the header line lists them).

Event ids are RenderDoc's (`draws` prints them), stable for one capture. The GUI shows the same ids.

On the host (Nushell), the GUI from nixpkgs: `nix shell nixpkgs#renderdoc -c qrenderdoc <file.rdc>` opens a capture.
To capture from `just play` yourself, run the game under the layer with the frames to capture, or a frame that never
comes plus RenderDoc's own capture key (F12 or PrintScreen while the game window is focused):

```nu
let rd = (nix build nixpkgs#renderdoc --no-link --print-out-paths)
with-env {
  VK_ADD_IMPLICIT_LAYER_PATH: $"($rd)/share/vulkan/implicit_layer.d", ENABLE_VULKAN_RENDERDOC_CAPTURE: "1",
  NX2NAVI_RDOC: "999999999", NX2NAVI_RDOC_DIR: "build/v111/captures", NX2NAVI_RDOC_DLL: $"($rd)/lib/librenderdoc.so",
  NX2NAVI_EXE: "rdoc",
} { just play }
```

Captures land in `~/claude/nx2navi/NX2navi/build/v111/captures/nx2navi_capture*.rdc` (the play log's `rdoc:` lines
map them to presents; expect about 10 GB each), which Tally sees at the same path: hand over the path and
`tools/rdc` answers from it. `qrenderdoc` on the host opens the same file; "File > Launch Application" works too, but
set `NX2NAVI_RDOC` in its environment block or the game requires the hidden extension and stops at device creation.
`NX2NAVI_EXE=rdoc` picks `nx2navi.rdoc` until patch 0026 is in the plain binary. HDR: the lab runs SDR; a native-HDR
capture holds the PQ swapchain, `rdc save` writes it as stored.

## Flatpak build kit (Steam Deck)

`flatpak/` packages a **build kit**, not the game: the toolchain (clang/lld 22, Python 3.12 and 3.14 venvs with the
requirements, the prebuilt shader translator), the upstream checkout at the commit `build` sits on with
`patches/*.patch` applied (0002 left out: only `build-xlate-private.py` uses it), `build-linux.py`, `runtime-linux/`
and the launcher `flatpak/nx2navi.sh`. Runtime: `org.freedesktop.Sdk//26.08` (it compiles at run time; SDL3, opus,
vpx, dav1d, zstd and the Vulkan loader come with it) and its GL extension for Mesa/RADV, so no nixGL.

**License: for Cal's own devices only.** Build it locally or take the private CI artifact and install with
`flatpak install --user`. Never publish it to Flathub, a remote, a release or a page. It holds no game files and no
keys; the game is built on the device from your own dump.

- `just flatpak` builds `flatpak/nx2navi-kit.flatpak` (needs network: pip wheels, NuGet for the translator).
  In a container without `/dev/fuse` add `--disable-rofiles-fuse` to the flatpak-builder line.
- `just flatpak-install` installs it for this user.
- CI: `.github/workflows/flatpak.yml` (manual dispatch, `kit-*` tags, pushes touching the kit or patches) uploads the
  bundle as an Actions artifact kept 3 days. Nothing else.

Without a built game the launcher opens the setup screen (`flatpak/setup.c`, SDL3 from the runtime): fullscreen,
D-pad, A and B only, so it works in Steam Deck Game Mode. It offers two routes:

- **Build from my game file (.nup)**, on the device itself. It scans the app data dir, `~/Downloads`, `~/Desktop`,
  the home dir and SD cards under `/run/media` (`--filesystem=home:ro` and `/run/media:ro`; portal choosers are
  unreliable in gamescope, so the portal is only an extra entry). Steps: unpack (`make_game.py --until romfs`),
  translate and compile (`build-linux.py --cpu v3 --jobs 6`: 6 compile jobs, one link, within the Deck's 16 GB),
  prepare shaders (`prepare_shaders.py`, which opens its own window). The progress screen shows the step, percent
  (ninja's count) with an ETA, the log's last line, a stay-plugged-in warning, and keeps the screen on. Each step
  leaves a stamp in `data/nx2navi/state/`, so quitting or sleeping resumes where it stopped. **Estimate on the Deck
  (Zen 2, 4c/8t), not measured: 3 to 5 hours in all**: about 30 min unpacking, 2 to 4 h compiling, 30 to 60 min shaders.
- **Import a prebuilt game (fast)**: a `*.nx2navi.tar.zst` made by `flatpak run io.github.dsktd.NX2navi export` on
  another machine (game folder, extracted ExeFS/RomFS and shader cache; no saves, logs or `nx2navi.ini`; about 30 GB).
  The import checks the export's kit id (same patches, glue and so runtime ABI), the game version, AVX2 for `cpu v3`,
  and that the binary and `romfs.bin` are there; this device's saves and settings stay.

With a game the launcher plays at once; `flatpak run io.github.dsktd.NX2navi setup` (or `setup` as Steam launch
option) shows the screen again, to rebuild or import. Terminal routes: `build [game.nup]`, `import <file>`,
`export [file]`, `status`.

Saves (`build/v111/profile`), `nx2navi.ini`,
the shader and pipeline caches and logs all live in that data dir, writable. A new kit re-copies the sources and
rebuilds the game; a new `.nup` re-extracts. Play defaults are the justfile's: `RADV_DEBUG=nogpl`,
`NX2NAVI_PIPE_SKIP=any`, `NX2NAVI_HDR=native`, `NX2NAVI_REPLAY_ASYNC=1`, `NX2NAVI_VK_RECORDER=1`,
`NX2NAVI_TEX_RELEASED_MIB=3072`, each overridable.
Permissions: Wayland (X11 fallback), `--device=all` (GPU and the Deck's pad), PulseAudio, `/sys/class/dmi/id` read-only
(Deck detection), home and `/run/media` read-only (the scan), no network.

### Steam Deck in one command

Prerequisites, once, on the Deck in Desktop Mode (Konsole): `passwd`, then `sudo systemctl enable --now sshd`; from
the desktop `ssh-copy-id deck@<deck>` (or type the password when asked). Desktop side: Nix (gh, flatpak, just come
from nixpkgs when not on PATH), the dsktd token at `~/.config/gh/dsktd.token` (read here only, never copied).

    just host=<deck-hostname-or-ip> deck                    # or: flatpak/deck-setup <deck> [local] [nup <game.nup>] [game <export>] [user <name>]
    just host=<deck> nup=/path/game.nup deck                # first time without a desktop build: send the .nup too

What it does, end to end:

1. **Kit.** If this desktop has the kit installed with a built game (`flatpak run io.github.dsktd.NX2navi status`
   shows `game` and `shaders` at the kit id), the Deck gets exactly that kit, bundled from the local Flatpak repo.
   Otherwise the newest `flatpak` workflow artifact of the private repo (`gh run download -n nx2navi-kit`), or, with
   `local` or when there is no artifact, `just flatpak` builds it.
2. **Game.** With a built desktop kit it runs `export` (about 30 GB, no saves; reused when an export of the same kit
   exists) unless `game <file>` names one. Without, it prints the two commands for that fast route and continues
   with the `.nup` route: `nup <path>` lands in the Deck's `~/Downloads`, where the setup screen finds it.
3. **Deck** (rsync, else scp, into `~/Downloads/nx2navi`; then over SSH as user `deck`): Flathub remote,
   `flatpak install --user` (`--reinstall` when already there: an update, app data stays), `import` of the export
   (this Deck's saves, `nx2navi.ini` and logs are kept), the copies deleted, and a Steam shortcut "NX2navi"
   (`/usr/bin/flatpak`, launch options `run io.github.dsktd.NX2navi`) written into every user's
   `config/shortcuts.vdf` by `flatpak/deck-shortcut.py`, only while Steam is not running (quit Steam in Desktop Mode
   first; otherwise it prints the manual "Add a Non-Steam Game" steps).

Then switch to Game Mode and start NX2navi from the Library: with an import it plays at once; with a `.nup` the
setup screen builds (3 to 5 hours, resumes when stopped, keep it plugged in).

**Update later:** re-run the same command. It ships the current kit (desktop's, or the newest artifact) and
re-imports the game; saves stay. With the desktop route, update the desktop first: `flatpak install --user -y
flatpak/nx2navi-kit.flatpak`, then `flatpak run io.github.dsktd.NX2navi build` (it rebuilds only what the new kit
changed), then `just host=<deck> deck`. The import refuses an export whose kit id differs from the Deck's kit, so the
two always match.

Manual route, if SSH is not an option: copy `nx2navi-kit.flatpak` and your `.nup` (or an export) to the Deck's
`~/Downloads` or an SD card, `flatpak install --user nx2navi-kit.flatpak` in Konsole, Steam > Add a Non-Steam Game >
`/usr/bin/flatpak` with launch options `run io.github.dsktd.NX2navi`, and start it in Game Mode. Allow about 60 GB
for a build, 30 GB for an import.
