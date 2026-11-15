# NX2navi architecture

How _The Legend of Zelda: Ocarina of Time_ for Switch 2 (game 1.1.1, build dir `v111`) runs as a native Linux x86-64 program here. Sources: the upstream worktree `~/claude/nx2navi/NX2navi` (branch `build` = upstream plus our private patches) and the tooling repo `~/claude/nx2navi`. Paths below are relative to `NX2navi/` unless they start with `~/claude/nx2navi/`. "Not established" means the code and logs read for this document do not answer the question.

## 1. What it is

NX2navi is a static recompiler plus a runtime. It takes the game's own ARM64 executable modules (ExeFS: `main`, `sdk`, `subsdk0`) and turns every guest function into a C function ahead of time. That C is compiled for x86-64 and linked with a hand-written C runtime. The runtime plays the role of the Switch 2 operating system (Horizon kernel, `nn::` SDK services) and of the GPU driver (NVN, translated to Vulkan). The game's data (RomFS: models, textures, shaders, audio, movies) is read at run time from the player's own dump. Out comes one executable (`build/v111/nx2navi`, 318 MB) plus caches. The game files, the generated C, the binary and our private patches are never redistributed (`tools/make_game.py:23-24`; every lifted file starts with "generated ... from game code. Do not edit or commit", e.g. `generated/v111/main/main_0049.c:1`; `~/claude/nx2navi/README.md`, "Private local patches").

## 2. Build pipeline

```
.nup dump --make_game.py --until romfs--> build/extracted/v111/{exefs, romfs/romfs.bin}
exefs --recomp/gen.py + patches-v111.txt--> generated/v111/{main,sdk,subsdk0}/*.c, layout.h, patches.h
       (+ the two SDK bring-up fixes, make_game.py:62)
generated C (-O1) + runtime/*.c (-O2) + runtime-linux/frames.c --clang/lld via Ninja--> build/v111/nx2navi
shaders in romfs/exefs --prepare_shaders.py + nx2navi_xlate--> shader-cache/, pipeline-cache.bin
```

- **Extraction.** `make_game.py` checks the title id `0x0400486024DEC000` (`tools/make_game.py:53`) and main's build id, unpacks the ExeFS segments and packs every RomFS file into one image with an index (`tools/make_game.py:8-14`). In this build that is 186,583 files and a 26.2 GB `romfs.bin` (play log lines 55-57).
- **Lift.** `recomp/lifter.py` decodes ARM64. `recomp/simd_c.py` lowers NEON and floating point. The output is one C function per guest function, named by its guest address (`f_7000001a20(Cpu *c)`), split into chunk files of many functions each.
  - Direct `BL` becomes a direct C call. Indirect branches go through `rt_dispatch` (`runtime/dispatch.c:207`), which looks the target up in an address-keyed table and tail-calls it. Tail branches use `musttail`. Jump tables are resolved symbolically (`recomp/jumptables.py`).
  - Registers live in a `Cpu` struct: `x[32]`, a separate `sp`, `pc`, `nzcv`, FP control and status, and the vector registers at offset 512 (`runtime/cpu.h:8-30`). NZCV and the six most-used registers of each function are kept in C locals and stored back around calls, SVCs and exits (`docs/architecture.md`, section 2).
  - Guest memory is addressed directly: guest address = host address. `LD64(a)` is a plain pointer dereference (`runtime/cpu.h:80`). The guest stack is guest memory pointed to by `sp`. Every guest `BL` is also a host call, so each guest thread gets a 256 MiB host stack (`runtime/kernel.c:5`).
  - An `SVC #n` becomes `rt_svc(c, n, pc)` (`runtime/cpu.h:37`). `UDF` and `BRK` become fatal traps.
  - The patch table (`recomp/patches-v111.txt`) replaces chosen instruction words at generation time.
  - 297,414 functions lifted (`~/claude/nx2navi/README.md`, "What was verified").
- **Translation units.** 489 (main) + 58 (sdk) + 4 (subsdk0) = 551 lifted C files, about 1.2 GB of C in `generated/v111`, plus about 136 runtime C/C++ files.
- **Flags.** Lifted code: `-O1 -fno-strict-aliasing -fvisibility=hidden -march=x86-64-v3`. Runtime: `-O2 -g -Wall -fdeclspec`. Link: `-fuse-ld=lld -no-pie`, plus Vulkan, SDL3, opus, vpx, dav1d and zstd (`~/claude/nx2navi/build-linux.py:45-53, 168-172`). Upstream uses the same -O1/-O2 split (`tools/make_game.py:605`). Measured: `-O2` and `-march=znver3` on the lifted code changed nothing (`~/claude/nx2navi/README.md`, "Guest optimisation level").
- **Where our build differs from upstream's Windows build.**
  - Upstream's kit (`make_game.py`) compiles Ocarina only with MSYS2 Clang on Windows. Upstream's Linux path (`build_game.py`) writes the glue for its other title.
  - `build-linux.py` runs the kit's lift and glue writer, then compiles with Linux flags through Ninja and ccache (`~/claude/nx2navi/README.md`, "How the build works").
  - It also compiles `runtime-linux/frames.c`. This fixes two Linux platform gaps: setjmp/longjmp through lifted frames, and fiber stack alignment. Upstream since 2026-11 has both natively; `build-linux.py` drops frames.c for such a checkout (section 10, upstream rebase).
  - The window is SDL/Wayland, not Win32.
  - A fresh worktree as `--src` lacks the gitignored generated headers: `runtime/*_spv.h` (tools/build_shaders.py),
    `runtime/smaa_area_tex.h`, `runtime/smaa_search_tex.h` and `runtime/ui/roboto_ttf.h`; copy them from a built worktree
    (rebase5, 2026-11-13: vk_aa.c failed on `smaa_area_tex.h`).
  - The glue is the same `modules.c` (`tools/make_game.py:386-388`): game version 111, a 9809 MiB application pool, NVN API 231.40.

## 3. Guest/host boundary

There are three ways across the boundary:

- **SVC trap.** `rt_svc` handles threads and sync (`kernel.c`), IPC (`ipc.c`), memory (`memory.c`) and GetInfo. The 21 SVCs never reached on the boot path stop with a named fatal (`runtime/svc.c:2-4`).
- **Hooked symbol.** `HOST_OVERRIDE("<mangled nn:: name>", fn)` replaces that symbol in every GOT/relocation of every module. `HOST_OBSERVER` wraps it and can still call the original (`runtime/host.h:108-111`). These host functions get synthetic guest addresses (`runtime/hostfn.c:1-6`). There are 295 overrides in total.
- **Function-pointer table.** NVN is reached through `nvnBootstrapLoader` / `nvnDeviceGetProcAddress`, which hand out host functions for 545 proc names (`runtime/nvn_procs.c:2`, `runtime/nvn_procs.inc`). Missing procs are traps that log their first call (play log lines 92-140).

| Subsystem                                           | Game code runs?                                                                | Replaced by (file)                                                                                            | Patched?                | How it crosses                                          |
| --------------------------------------------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------- | ----------------------- | ------------------------------------------------------- |
| Kernel: threads, sync, virtual cores                | `nn::os` is lifted and runs; only the kernel below it is host (`kernel.c:5-8`) | `runtime/kernel.c`: one host thread per guest thread, 6 virtual cores (`kernel.c:29-30`), priority preemption | no                      | SVC                                                     |
| Kernel: fibers                                      | the game's job code is lifted                                                  | `kernel.c:2396-2399`                                                                                          | no                      | override of `InitializeFiber`, `SwitchToFiber`, ...     |
| Kernel: memory                                      | no                                                                             | `runtime/memory.c`                                                                                            | no                      | SVC (SetHeapSize, MapPhysicalMemory, QueryMemory)       |
| Handles, IPC, `sm:`                                 | client side lifted                                                             | `runtime/ipc.c`: in-process IPC; only `sm:` and `audren:u` are real services (`ipc.c:3, 186-198`)             | no                      | SVC 0x21 SendSyncRequest                                |
| fs / RomFS                                          | no                                                                             | `runtime/romfs.c:1281-1284` (`MountRom`, ...), `runtime/fs_host.c`                                            | no                      | override                                                |
| Saves                                               | no                                                                             | `fs_host.c`: a host directory plus a working copy committed on `Commit` (play log 339-342)                    | no                      | override                                                |
| hid / input                                         | no                                                                             | `runtime/ov_input.c`, `input.c`, `input_sdl.c` (SDL3)                                                         | no                      | override                                                |
| Audio out                                           | `nn::atk` (sound engine) is lifted and runs                                    | `runtime/audren.c`, `audio_mixer.c`, `audio_effects.c`: host audio renderer, SDL output                       | no                      | IPC `audren:u`                                          |
| vi / display, HDR queries                           | no                                                                             | `runtime/ov_gfx.c:178-185`                                                                                    | no                      | override                                                |
| time, settings, account, applet, oe, pctl, aoc, err | no                                                                             | `runtime/ov_system.c` (85 overrides), `net_offline.c` (57)                                                    | no                      | override                                                |
| NVN graphics                                        | the game's renderer is lifted and runs                                         | `nvn_api_core.c`, `nvn_api_cmd.c`, `nvn_api_obj.c`, `nvn_tex.c` front end; `vk_*.c` Vulkan back end           | no                      | proc table                                              |
| Shaders                                             | the game's binaries are used as data                                           | translated by `nx2navi_xlate` (section 7)                                                                     | SPIR-V post-passes      | from the NVN program object                             |
| Movies                                              | no                                                                             | `runtime/ov_movie.c`, `ov_movie2.c` (AV1 via dav1d, play log 436)                                             | no                      | override                                                |
| Physics / middleware                                | lifted if present                                                              | none                                                                                                          | no                      | none; whether Havok is in this title is not established |
| Fonts                                               | the game's text rendering is lifted                                            | the menu overlay only reads the game's fonts (play log 60)                                                    | no                      | none                                                    |
| Memory allocators (game heaps)                      | lifted (sead and game allocators)                                              | the region underneath is `memory.c`                                                                           | no                      | SVC                                                     |
| Job system                                          | lifted; fibers move between workers (`kernel.c:115-117`)                       | fiber primitives only                                                                                         | no                      | override                                                |
| Frame pacing, game step                             | the game's own controller runs                                                 | `runtime/frame_rate.c`                                                                                        | `ostep` set (section 8) | patch page                                              |
| `memcpy`                                            | no                                                                             | `nvn_api_core.c:74`                                                                                           | no                      | override                                                |

- **Save states are not possible as built** (DESIGN-savestate.md, 2026-11-11). Every guest `BL` is a host call (`kernel.c:5`), so a thread's guest call chain lives in its 256 MiB host stack (`mmap(NULL, ...)`, ASLR'd, `platform/linux.c:335`) as host return addresses and host pointers. `Cpu` holds only the innermost registers. Guest RAM and GPU state could be restored; the threads cannot be, short of CRIU, and the container has no checkpoint capabilities.

## 4. Game components used as they are

Identified inside the lifted code:

- **The engine framework.** There is a sead-style engine framework: sead perspective projection and viewports (`recomp/patches-v111.txt`, wide_aspect and wide_movie comments) and sead delegate lists (`~/claude/nx2navi/NOTES-fog-nan.md:512`).
- **The framework's per-frame update** at `main+0x6e6be0`.
- **The time manager** at `**[main+0x4c7e890]`, fed its nominal frame through `main+0x3b4e300` (`recomp/patches-v111.txt:21-28`).
- **The adaptive present-interval controller.** Upstream documents it at `main+0x8f26c8` for its other title (`runtime/frame_rate.c:4-9`). For Ocarina the log says "no patch table, shipping 30 fps whole-vsync steps" (play log 42). The Ocarina equivalent is not established.
- **The graphics setup** at `main+0x1202ce0`: it presents 2560x1440 and the scene is 1920x1080 (`patches-v111.txt`, wide_out and wide_scene).
- **A dynamic-resolution controller** (`main+0x805bd0`).
- **The camera update** (`main+0x4c48c0`).
- **The 2D UI canvas** (`main+0x774330`).
- **nn::atk** with its sound thread, per-frame update `main+0x36d1440` and stream loader `main+0x6cb2d0` (`~/claude/nx2navi/NOTES-fog-nan.md:512-543`).
- **The game's tensor-core temporal upscaler shaders.** They are drawn but replaced by a plain scale (`docs/architecture.md`, section 4; patch 0012).

Not established: Havok, a font rasterizer, the job scheduler's identity, and the guest thread count.

Read at run time:

- RomFS files through the index (`romfs-index.bin`, 186,583 files).
- Shader programs (NVN control section plus code, found by `tools/shader_census.py`).
- Textures, mostly ASTC, decoded on the GPU and re-encoded to BC3 (play log 141-143).
- AV1 movies.
- Saves in `build/v111/profile/save` (14 files, 1.0 MiB; play log 340-341).

## 5. One frame, end to end

```
 guest threads (lifted)              host runtime                         GPU
 ----------------------              ------------                         ---
 main thread 0x1003 + 4 job workers --nvn*--> nvn_api_cmd.c records op
  (guest code 4 ms each per frame)            streams into host buffers
        |
 nvnQueueSubmitCommands ---------> nvn_submit_prepare; hand-off
   (finish wait 9.3 ms: for the     [frame bound: game at most 1 frame ahead]
    replay thread, then the GPU)        |
        |                          replay thread (vk_exec*.c), ~22 ms per frame, THE BOUND:
        |                           texture pool refresh (2.7-3.2 ms field)
        |                           shadow sync of guest pages (2.8-3.1 ms)
        |                           uniform snapshot (0.5 ms, vk_usnap)
        |                           pipeline lookup / build or skip
        |                           draws, mesh draws, compute
        |                               | packets (ring)
        |                          recorder thread (vk_rec.c) vkCmd* ---> queue (GPU busy 10 ms)
        |                               |                                  |
        |                          completion thread (vk_sync.c) <------- timeline
        |                           write-back compare (4.2 ms, 4 thr)
        |                           write-back, frees, events
 presenting thread 0x1008 (sleeps until the main thread wakes it, then 4 submits)
 nvnQueuePresentTexture --> pacer (nvn_api_obj.c:737-752) --> vkQueuePresent (mailbox)
```

- **Recording.** The game records NVN command buffers. Records go to growable host buffers, never into the game's command memory (`runtime/nvn_api_cmd.c:1-12`).
- **Replay.** At submit, the replay walks the ops (`runtime/vk_exec.c:1-10`). It runs on its own thread at most one frame behind the game (play log 316). A recorder thread makes the driver calls from a ring (`runtime/vk_rec.c:1-6`).
- **Completion.** One timeline semaphore orders everything. A completion thread runs the CPU-side effects per value (`runtime/vk_sync.c:1-9`).
- **Draws.** Mesh and task shaders run through `VK_EXT_mesh_shader` (play log 18). Textures are bindless pools: 16 kinds x 32768 slots (play log 49).
- **Present.** The present goes through the pacer, then `vkQueuePresent` in mailbox mode.

Costs per frame in the Hyrule Field standing window, lab replay of Cal's 19:13 recording, mean frame 23.4-25.9 ms, 40-43 fps (`~/claude/nx2navi/NOTES-perf-2026-11-09.md`, "Round 3"; `NX2NAVI_TRACE=nvn` and `perf`):

| What                                          | Thread            | Cost         | Notes                                                                                       |
| --------------------------------------------- | ----------------- | ------------ | ------------------------------------------------------------------------------------------- |
| Translating and recording a frame             | replay            | about 22 ms  | the bound; notes "After fixes 1+2", section 4                                               |
| of it: texture pool entry refresh             | replay            | 2.7-3.2 ms   | 32.8k slots walked, 17k refilled, 5.7k storage checks; 6.3 ms in the graveyard              |
| of it: shadow sync                            | replay            | 2.8-3.1 ms   | 915 pool syncs, 10 MiB copied; write-watch queries 1.5 ms                                   |
| Submit finish wait (`nvnQueueSubmitCommands`) | main 0x1003       | 9.3 ms       | waits for the replay thread to record and submit the frame's first submission, then the GPU |
| Waiting for the job workers (`svc 0x34`)      | main              | 7.9 ms       | 23 waits per frame                                                                          |
| Guest code                                    | main              | 4.1 ms       | 16% of its frame                                                                            |
| Guest code / runtime calls                    | each of 4 workers | 3.8 / 1.6 ms | idle the other 20 ms                                                                        |
| Sleep until woken by the main thread          | presenting 0x1008 | 24.6 ms      | then 4 submits and the present                                                              |
| GPU busy                                      |                   | 10.2 ms      |                                                                                             |
| Write-back compare                            | completion        | 4.2 ms       | 66 MiB compared, off the frame's path                                                       |
| Audio mix                                     | audio             | 1.5 ms       |                                                                                             |
| Pipeline binds                                |                   | about 690    |                                                                                             |

- **What the replay thread spends.** About a third is libc and kernel, not runtime code: shadow-sync memcpy, write-watch (PAGEMAP_SCAN) and submit ioctls, RADV re-creating the gang (ACE) follower preamble on every submit that holds a task-shader draw (Mesa 26.2.6 `radv_update_gang_preambles` has no early return); compiler flags (-O3, znver3, ThinLTO) change nothing (NOTES-perf "Runtime optimisation").
- **Where the game waits.** In the submit finish wait, which is the replay thread's backlog, and on `pool_fini` at area changes.
- **Ground-fog pass (#174).** Fog-volume areas (Lost Woods f298999 passes 0158-0161, ice cavern f1046 pass 0190) draw ground fog at half res: 0158 renders the fog mesh's depth only (ts 545f1eca, ms 2f4c1fee, into a 960x540 d32f), 0160 shades it (ts 545f1eca, ms a38b6ce1, fs 560e3938) into two rgba16f 960x540 targets (t1 = fog colour), depth-tested against the half-res scene depth that also comes in as texelFetch slot 2 (linearised with c3[189]); slot 1 is the fog-mesh depth (discard behind it), slot 5 the full-res rgba8 AO/contact-shadow mask (B = Link's blob shadow, read as 1-z), slot 8 the 4x4 tex 258. The full-res fog composite (f298999 pass 0179, fs 3bdeddef) adds t1 (tex 21757) to the HDR scene. The "Link ghost" (pale patch beside Link's legs/shield) is already in 0160's t1, bounded by Link's half-res silhouette, and absent from every depth and colour target before it; f1046's t1 shows the same bright fringe on Link's left. Which term of fs 560e3938 makes it is not yet known.
- **#174 live A/B (play13, Lost Woods, logs/shot-01686..06551).** Discarding fs 560e3938 removes the ghost; forcing both scene-depth reads of that shader to 1.0 removes it too (fog stays, thinner; #157's bottom-left strip weaker); dropping the blob-shadow factor (slot 5 .z) or forcing the slot 8 lookup does not. The two reads (texelFetch slot 2 = 960x540 d32f scene depth, linearised with c3[189]/c3[191]): read 1 at the fragment's own pixel (_84 scales by support_buffer m5[2]); read 2 inside the ray-march, a world point projected with c3[7]/c3[8]/c3[10] to uv, times c3[18].xy to pixels, compared with the sample's depth. Fault not yet pinned: needs the c3 values (c3[18] size vs 960x540; c3[7..10] jittered or not) from a live `dump.req` with `ubo=`.
- **#174 read 2 is the fault (live, play13).** Forcing only the ray-march depth read (b2b) removes the halo and the edge bands with the fog kept; read 1 alone (b2a) changes nothing. Dump f26029 (pass 0156): the projection rows the read uses, c3[7]=(1.20628,0,0,0), c3[8]=(0,2.14451,0,0), c3[10]=(0,0,-1,0), are a plain 16:9 unjittered projection identical to the scene VS's (c13[8..11]), so the projection is not it. Still unread: c3[18] (pixel size), c3[189]/c3[191] (depth linearisation), support_buffer m5 (`ubo=1` prints only 16 vec4; ask for `ubo=192`). Open suspect: samples projected off-screen or across Link's edge fetch out of bounds or the wrong texel (robust OOB fetch returns 0, vk_device.c enables all supported robustness).
- **#174 constants (dump f32202, ubo=192, fog pass 0155).** c3[18]=(960,540,1/960,1/540) matches the depth texture; c3[189]=(25000,-24999.9), c3[191].x=2500: linear z = -2500/(25000-24999.9 d), standard Z (0 near, 1 far), so an out-of-bounds fetch returning 0 reads as "at the near plane" = occluded. Clamping read 2's pixel to the texture (b4clamp) removed the edge bands live, the halo stayed. Slot 2 is a copy of the half-res depth (copy after pass 151, 0x8002418a00 -> 0x8004644200), also the pass's depth attachment; nothing writes it between copy and fog (0152-0156 depth images identical in range/count). The halo is not explained by constants, sizes or a stale target.
- **#174 edge bands fixed by clamping texel fetches (patch 0081).** Switch 2 footage of the Lost Woods entrance shows neither the halo nor the edge bands (its fog is also denser and bluer, but the footage shows child Link). `NX2NAVI_TLD_CLAMP=1` clamps every texelFetch in the translator (`tools/xlate/patches/0036-texel-fetch-clamp.patch`, HostOptions.TldClamp, set per job by Program.cs from `tld_clamp`; runtime/gfx_shader.c mixes it into the translator identity). The halo is still open: it is read 2 too, but not out of bounds and not the constants. Building a translator: in a worktree, set `GIT_CEILING_DIRECTORIES` to the parent of the `--out` dir. Otherwise git apply silently skips the new-file patches (0021 PRMT, 0036).
- **SKIP_SHADERS and live swaps on mesh draws (#174).** `NX2NAVI_SKIP_SHADERS` acts only at draw time (`runtime/vk_exec_draw.c` shader_skipped, checked after the shaders resolve and before any pipeline lookup, the same path for vertex and mesh draws); it never reaches pipeline creation. The start crash `libvulkan_radeon.so+0x19be92 writing 0x40` right after "4 background graphics pipeline workers" happened with that knob (play-20261111-170227) and also without it on 2026-11-10 (play-20261110-225615), both with plain `just play` on `pipeline-cache.bin`; the i2f recipes have not shown it. Hot-reload files of mesh-pipeline fragment shaders are named like any other: `<sha256 cache key>.spv` in the watched dir (`shader-cache-i2f` for the try recipes). Find one by `cmp` against the dump's `sh_<fnv>.spv` (fs 560e3938 = i2f `eeb937a7...`, byte-identical to plain `591303b6...`); a `.res.json` beside it has the same body minus `key`.
- **The critical path.** The replay thread. "frame bound 1800 calls, 0 waited" only says the present never waits for it; the game waits for it in the finish wait instead. Letting the game go before the GPU is through (`NX2NAVI_FINISH_DEFER`, patch 0036) gains nothing, and neither does faster guest code (16% of the main thread; the -O2 A/B agrees): what shortens the frame is a cheaper replay thread per draw.
- **Native replacements, ranked (2026-11-12, play49 f12f898, `STUDY-native.md`, desk study from p49.prof and fc-bstat-1, no A/B).** Field f2663 standing: 3,250 draws a frame (BIND_STATS), ~3 us of replay a draw; GPU busy 12.0 ms with 5.6 ms starved (`perf: frame N: GPU timeline`), so the GPU is not the bound above ~12.5 ms. The FINISH_DEFER "gains nothing" above was measured on the 22 ms replay; under dma-buf the replay idles 4.0 ms a frame in `replay_main`'s `plat_cond_wait` and the interval is replay + ~4.6 ms, so game/replay overlap is again the largest lever, ahead of a resolve cache (2.6 ms of `shader_for`/`graphics`/`feedback_prepare`/`bind_vertex_buffers`) and buffers as device addresses (xlate 0030 already reads global memory through `vk_gpa.c`'s table). Hand-written shaders and 240 Hz pacing win 0 ms now.
- **Draw recording on build 701e7ce (2026-11-15, exe slim2, f2663 capture cell x1, `.lab/pde/slim2.prof` presents 3300-5300, indicative; lab without `/dev/udmabuf`, so shadow storage and 6 automatic replay workers).** 40.1 fps, replay 16.0 ms, GPU 10.6 ms. On the submitting thread per frame: `prepare_draw_ex` 2.5 ms (`bind_resources` 1.7, of which 0.5 ms is `vk_exec_turn` spinning in `pool_sync_draw` when a chunk takes the submission's texture-pool set, `vk_exec_draw.c`), `walk` self 2.0, `vk_mem_shadow_sync` 2.3. The play49 split (prepare_draw_ex 8.3 ms) predates the workers and no longer describes the build; re-profile with dma-buf before choosing a #132 lever. With dma-buf (same day, `.lab/pde/slim2.prof`): 55.5 fps, replay 13.2 ms, and the replay runs on the `guest [render]` thread: `prepare_draw_ex` 4.7 ms a frame (`bind_resources` 2.9, `vk_exec_turn` spin 0.5), `walk` self 2.0, `counter_word`+`report_counter` 0.6. Taking the pool set at `vk_exec_draw_group_begin` instead of in a chunk's turn (knob tried as `NX2NAVI_POOL_GROUP_TAKE`, exe pde1, ABBA x3) gained nothing measurable (56.2 vs 56.0 fps mean, spread 54-58), so it was not kept. The lab container must have `/dev/udmabuf` (log `mem: guest memory is a memfd's`) for lab numbers to match Cal's play.

- **Frame capture (`runtime/vk_capture.c`, patch 0083).** The narrowest seam for a standalone replay is `GfxBackend` (gfx.h): pools, slot registrations, submit(handles), present. Op records point at guest objects (`prog_t`, `dpool_t`, control sections, event words: below 2^39, restored at their address after `mem_init` reserved the same block, checked) and at host texture pins (relocated). The shadow sync (`vk_memory.c shadow_copy`) runs *after* recording a submission, so it shows what the GPU got, not what CPU-side reads (usnap, texture uploads) saw at record time. `VkExec` (vk_exec.c `X`) carries state across frames (bound state objects, channel masks, pools, bindings): a replay must load it (`vk_exec_state_load`). The default `NX2NAVI_PIPE_SKIP=any` skips draws whose pipeline is still building, so replays set `strict`. Replay fixes found: memory.c must see the guest ranges as mapped (heap grown with mem_set_heap_size, alias pages mapped), else `mem_readable` refuses texture uploads ("storage not mapped"); write only pages that change (a written page counts as a CPU write and re-uploads mirrored textures); physical-pool images alias pool memory, so restoring the pool bytes is their content. Open (2026-11-11, f1499 LAB_SOFT load menu): the replayed picture equals the start content (35.1 dB vs final.png) and does not change when draws are skipped (14, 26-153, 154); pass 1 replays exactly like the game's, but the 1280x720 blur chain (passes 2-13) reads a texture at 0x8000000000 that aliases a 1920x1080 rgba8 image in the same physical pool and comes out NaN, and pass 14's draws leave the dumped target unchanged.

## 6. Memory model

All guest addresses are below 2^39 (`docs/architecture.md`, section 2). `runtime/memory.c:215-248` reserves:

- The module window at `0x7000000000`. Main is 0x4ea0000 bytes, subsdk0 sits at `0x7005000000` and sdk at `0x7005200000` (play log 36-38). The patch page sits right after main, at `0x7004ea0000` (play log 39).
- A 14 GiB stack-and-heap block: a 256 MiB stack area and a 12 GiB heap cap (`memory.c:22-26`).
- A 64 GiB alias region for MapPhysicalMemory (`memory.c:27`).
- Kernel and host-function windows.

The game is told its application pool is 9809 MiB, as on the console (`memory.c:26, 30`; `make_game.py:387`). `NX2NAVI_APP_POOL=<bytes>` overrides it (`memory.c:238-248`). Patches 0034/0035 log SetHeapSize and MapPhysicalMemory high-water marks and refusals.

GPU-visible NVN memory pools map onto Vulkan memory in one of two modes:

- **Import mode.** Host memory is imported into Vulkan directly (`VK_EXT_external_memory_host`).
- **Mirror mode** (the default on a discrete GPU, play log 17). Pools used as buffers get a device-local mirror, and the pages the CPU wrote are uploaded.

On Linux, shadow storage is on (play log 16; `runtime/vk_memory.c:921-933`). Each CPU-visible pool gets its own host-visible buffer, kept in step both ways:

Upstream PR #730 (9772002, not merged; our branch `dmabuf` = play48 + it, exe play49) replaces the shadow copies with dma-buf imports of a memfd-backed guest memory through `/dev/udmabuf` (`runtime/platform/linux.c`, `runtime/vk_memory.c` "dma-buf imports"; knobs `NX2NAVI_DMABUF`, `NX2NAVI_DMABUF_MB`). It falls back to shadow storage when `/dev/udmabuf` is missing or not read-write (log `mem: dma-buf imports off`). Host kernel has `CONFIG_UDMABUF=y`, `size_limit_mb` 2147483647; the lab container has no `/dev/udmabuf` (2026-11-12), then (fixed the same day by passing the device in): with it, play49 logs `mem: guest memory is a memfd's: CPU-visible pools are imported as dma-bufs`. Hyrule Field f2663 standing (windows 1800-3000), game on cores 0-7,16-23: play49 51.6-52.8 fps vs play48 40.7-42.0, replay 14.6 vs 19.3 ms, GPU 12.4 vs 12.0 ms; the frame interval is replay + ~4.7 ms, so the frame stays bound by the replay thread. (`.lab/fc.sh` before 2026-11-12 19:40 averaged in the window after the last frame, a ~360 ms exit stall, so its fps were about half the real figure, the earlier "lab ~22 fps" included; `.lab/rs.sh` recomputes cells from run.log.) Replay thread on play49 there (`NX2NAVI_PROFILE`, presents 1800-2990, .lab/fc-prof/p49.prof): per frame 14.5 ms work + 4.0 ms in `replay_main`'s `plat_cond_wait` (waiting for the next submission). Of the work, `vk_exec_record` walk 11 ms: `prepare_draw_ex` 8.3 ms (`bind_resources` 4.8, `shader_for` 1.0, `tex_info` 0.6, `ubo_info` 0.6), `bind_vertex_buffers` 0.6; sync is small now: `pool_sync` 0.9 ms, `vk_mem_mirror_begin` 0.65 ms (its write-watch ioctl 0.55). So under dma-buf the next lever is draw-recording CPU, not shadow sync. Not suspects there (checked 2026-11-14 on rebase5, deckres, rebase6, v0.10.2-rc1): `vk_exec_draw.c` builds at the normal -O2 since patch 0006 (no -O0 left in the build scripts; only tests/flags_check.py uses it), and upstream 42ae87b's runtime speedups are in every current lineage (0073 port, then upstream history). `NX2NAVI_REPLAY_WORKERS=3` did not help there (47.1-49.9 vs 49.0-51.1 fps, 3 runs each). Descriptor builds there (`NX2NAVI_BIND_STATS=1 NX2NAVI_TRACE=perf,gfx`, `vk_exec.c` `vk_exec_frame_log`): about 3,300 `bind_resources` calls a frame, 5.4-6.3 ms timed (buffers 1.8, push 1.3, textures 0.7, signature 0.4 ms, the rest loop and `pb_entry`); per draw 4.7 vertex + 9.1 fragment descriptors, 60% of them kept (`pb_take`, BIND_REUSE), 0.9 pushes, 0.035 push skips. The descriptor build skip (`bind_skip_on`, which compares only with the draw just before) spares 5.1% of draws although 50.8% have the same program and state as the draw before and 12.5% also the same buffers: what differs is mostly the bound buffers' addresses (per-object uniform blocks), so a skip keyed on the previous draw alone cannot hit more.

Where the descriptor time goes, and why dynamic-offset uniform buffers were not built (2026-11-12, same profile `.lab/fc-prof/p49.prof`, play49 f12f898, 1190 presents, read with `tools/prof-window --tree` at a 0.08% threshold; derived from the profile, no A/B). `bind_resources` is 4.48 ms a frame: `pool_sync` 0.92 (the texture pool set's per-submission refresh, not per draw: `pool_sync_entries` returns at once while the generations stand), its own loop 1.02 (with `bind_sig`, `pb_entry` inlined), `pb_take` 0.59, `tex_info` 0.59, `ubo_info` 0.53 (`vk_usnap_find` 0.24), `ssbo_info` 0.21, libc copies and compares 0.18, `pb_keep` 0.06. Writing the descriptors is the small part: `rec_push_tpl` 0.09 ms a frame (about 0.03 us a pushed draw: a packet for the recorder thread, `vk_rec.c`), while the 7% of draws whose set is allocated (over 32 descriptors, `VkPipeInfo.push` 0) cost 0.13 ms: `alloc_set` + `vkUpdateDescriptorSetWithTemplate` + the bind, about 0.5 us each, on the replay thread, because a set update is no `vkCmd*` and is not handed to the recorder. `VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC` cannot be in a push set, so it would turn the 90% pushed draws into allocated sets: each draw whose set is not reused pays about 0.3-0.5 us more than its push, each reused one saves at most the 0.03 us packet and a compare, and every draw still resolves its uniform ranges (`ubo_info`) to know the offsets. With at most half the draws equal to the one before (same program and state 50%), that is a loss of several tenths of a ms a frame on the replay thread; the ceiling with every set reused is about 0.3 ms (push packets and compares) plus part of the 0.4-0.7 ms the replay waits for the recorder at part ends (`rec_end_cb`, `rec_drain`; pushes are about 1.3 of the ring's 2.3 MiB a frame). New set layouts would also change every pipeline's layout, so the driver's pipeline cache (`pipeline-cache.bin`) would compile all of them again. Patch 0113 (`NX2NAVI_BIND_STATS=1`, `bind_stats_reuse`, exe `p49stat` a1f225f, branch `bindstat`) counts what a cache of sets (equal but for uniform, or uniform and storage, offsets: against the build before, this command buffer, the last builds) or of builds (inputs equal to an earlier build's in this submission or command buffer) would reuse, and for builds with the pipeline info of the one before, which descriptors differ; built, not yet run on the GPU (Cal playing), so the reuse rates are unknown.


- **CPU to shadow:** before each submit, the written pages are copied into the shadow.
- **GPU to guest:** after the fence, GPU writes are copied back, page by page, only where the bytes changed (our patches 0001, 0008, 0025).

Written pages are found with a userfaultfd in asynchronous write-protect mode plus `PAGEMAP_SCAN`. This needs Linux 6.7, and Podman's default seccomp blocks it (`runtime/platform/linux.c:796-799`; `~/claude/nx2navi/README.md`, "Upstream bug").

Two lifetime mechanisms keep graphics objects alive just long enough:

- **Texture pins.** Recordings name immutable host copies of each texture initialisation. A copy is freed some submits after nothing reads it (`runtime/nvn_api_cmd.c:234-248`; play log: "6625 live, 6605 waiting").
- **Released textures.** See "Texture cache" below.

**Actor ambient and the sky-SH block (2026-11-12, play49 nx2navi.play49 f12f898, xlate-play33 e8d52df6; dumps f117977
f145806 f151860 f157171 f161901, shots 117512/138103; SYMPTOMS "Actors black at night").** How actors are lit, from
the rock fs `e99e29b92bdf88e6` (spirv-cross of `dump/f3781/sh_e99e29b92bdf88e6.spv`, cache keys 3386cff8/87c3b25c/855fbdc5):

- Fragment storage buffers are pointers in c0: s1 = c0+0x510, s2 = c0+0x520, s3 = c0+0x530, s0 = c0+0x540, matching
  the bound list 0..3 of the draw. s1 = 0x25ea76000 (cluster light lists, indexed by froxel from c3[148..151]), s2 =
  0x25fe26040 (light records, 96 B, the point lights: Navi), s3 = the sky-SH block 0x25a4c7f00, s0 = 0x27ef0d000
  (0xafc80 = 5000 per-object SH records of 144 B; record 0 stays zero).
- Ambient = hemisphere term (c6[73]/c6[74] by normal.y) + record `c4[14].x` of s0 (L0..L2, read at `_155`) x AO
  mask (tex 32318 .z/.w, pass 0201) x moon shadow, plus the env cube 751 term; the fog branch (`_434`, depth range
  from the 4x4 rgba32f tex 876) scales it. Direct lights are summed separately (`_590..594`), which is why Navi still
  lights a black rock.
- `c4[14].x` comes from an inline uniform update in the command stream, so a dump's `ubo=` shows the memory value (0),
  not the one the draw used (1407 for the rock, read by a hot-reload diagnostic). Do not trust dumped c4 for per-draw
  indices.
- The records are baked each frame by cs `a783a7570d45881f` (pass 0015, 8x128 threads, first submission) from the
  probe data (0x1af9d5000 via the pointer table 0x1af9b6540) and the sky-SH block words 12-27 (0x25a4c7f30..f6c). The
  game zeroes that block on the CPU each frame (writer `nx2navi.play49+0x22a64b9`, watch.req); cs `23e49873be2e1db2`
  (pass 0097, 1x1x1 from the sky texture 742, second submission) fills it. GPU snapshots (`buf=0x25a4c7ec0:0x140`):
  words 12-27 are 0 from frame start through pass 0015 and become non-zero only at 0097. So the bake never sees a sky
  term in our replay; the rock's record held L0 ~0.05 at night and the ambient fell to the hemisphere fallback.
- Cause, confirmed by Cal (2026-11-12, play49 with `NX2NAVI_REPLAY_ASYNC=0`, log play-20261112-204822: rocks and Link
  stay lit at night): async replay timing. The game zeroes the block right after it submits the frame's first
  submission (the sync replay records that submission inside the submit call, before the zero); the async replay
  records it up to a frame later, and the VRAM mirror takes the CPU's writes at the submission's first access to the
  pool (`vk_memory.c` `mirror_sync`), so the bake read the zero meant for the second submission's sky pass. Upstream
  0533b30 turned async replay off because it "can show a dark or flickering frame now and then".
- Fix 0114 `NX2NAVI_ASYNC_HOLD=<addr>:<size>[,...]` (default empty = off; async replay only; Ocarina:
  `25a4c7f00:100`): for the listed ranges the mirror takes the CPU's writes in submission order. `vk_usnap_take` copies
  them at the submit call (`vk_mem_hold_take`), `vk_usnap_begin` (adopt) hands the copy to `vk_mem_hold_begin`, which
  queues the words that changed since the previous submission's copy; `vk_mem_mirror_prologue` writes them into the
  mirror (`hold_record`, vkCmdUpdateBuffer) after the uploads and before the write-back merge's base copies, and
  `mirror_sync` leaves the ranges out (`pend_add`). A range whose pool has no mirror is left as before.
- 0118 `NX2NAVI_SSBO_SNAPSHOT=1` (default 0; exe ssnap, `runs/ssnap.sh`): the same ordering for storage buffers the
  game binds with nvnCommandBufferBindStorageBuffer, up to 256 KiB from the bound address: `vk_usnap.c` `collect`
  copies them at the submit call with the uniform blocks, and `vk_exec_draw.c` `ssbo_info` binds the copy when the
  shader only reads it (drop and in-flight rules as for uniforms; the arena has storage usage). For a Zora whose
  lighting flickered in daylight under async replay (Cal 2026-11-12 on texchurn, dump f9583; REPLAY_ASYNC=0 fixed it).
  Not covered: buffers shaders reach through addresses in constants (`r->ptr`, such as the sky-SH bake's), which
  stay with 0114's list.

### Texture cache (`runtime/vk_texture.c`)

Bindless slots (`TexSlot`, 16 kinds x 32768) hold the game's NVN descriptors. An entry (`Tex`) is a Vulkan image keyed by descriptor (`TexKey`: address + format/size/target...), found by key (`by_key`) or by storage address (`by_addr`, chained by `next_at`).

- **Live vs released.** `nvnTextureFinalize` releases an entry instead of destroying it (`released`, `rel_serial` = registration serial at release), so a re-initialisation of the same key takes it back with its content. Released entries go on a capped list (2048 entries; `NX2NAVI_TEX_RELEASED_MIB`, 3072 in `just play`, 1536 + `TEX_RELEASED_LRU=1` in `try-vram`). When a released entry is destroyed its key goes to the `gone` map with its serial (0066).
- **`slot_resolve` (vk_texture.c `slot_resolve`, ~2107).** A slot whose own entry is live uses it. Otherwise, in order:
  1. _Follow by address_: a live entry at the same address with the same target. A swizzle-only difference wins; otherwise the first other one (`any`). CPU-written (mirrored) slots follow only entries holding GPU content (glyph atlases reuse freed memory at other widths).
  2. _Follow another descriptor_ (#172): a GPU slot following an entry of another size or format is logged (`vk: slot N ... follows another descriptor`, first 32). A storage image bound so is written only where the two overlap: the 56.6% seam was a 960x540 blur store into a leftover 1696x129 r11g11b10f entry. `NX2NAVI_TEX_DESC_STRICT=1` (0079, default 0) resolves to the slot's own descriptor instead. Lab 2026-11-11 (seam replay, f10540, GPU, indicative): strict 0 ends on a near-black frame, strict 1 renders the Fire Temple scene correctly; no FATAL or device loss in either.
     `TEX_DESC_STRICT` acts on GPU slots only (`!cpu_slot`): CPU-rasterized UI glyph/caption atlases (#155 ocarina "Play a note" drawn as a stretched + icon, #163 nameplate garbage) are not covered by it. The play-20261110-141203 log around marks 59968/61847 has no `follows another descriptor` or stale/gone lines, so the wrong-image path for those is not yet identified (needs a dump at the bad frame).
  3. _Stale rule_: a CPU slot registered at or before its own entry's release is stale and resolves to nothing (prevents uploading from storage being unmapped). Ocarina finalises and re-initialises terrain height tiles (r32f 260x260) at the same storage without re-registering the pool slot, so they went to the dummy (#149/#169 holes and columns). `NX2NAVI_TEX_STALE_LIVE=1` (0074, default 0, on in `try-vram`) takes the entry back when `nvn_tex_live_at` shows an initialised texture of the slot's own key there. Lab: 3974 tiles recovered, 0 unresolved.
  4. _Gone rule_: own entry destroyed, slot registered before that. Default: a new **live** entry is made from the old storage (no Finalize ever releases it: a source of #160 growth). `NX2NAVI_TEX_STALE_GONE=1` (0066) resolves to nothing, but only when no live entry is at the address (0068; the unconditional version blanked live terrain).
  5. Else `entry_of` makes the entry from storage (bounded by the create budget during pool refresh).
     Every nothing-path is counted per path (stale, gone, create held, create failed) in the `mem: textures` line; the first 16 of each are logged. A dump's `tex N unresolved (dummy)` says why (0070).
- **Stand-ins and bindless handles (2026-11-12, dump f3781 play24).** A slot that resolves to nothing samples a 1x1 stand-in (`vk_exec_draw.c` `make_dummy`). On rebase-upstream (977acc7) these are never cleared: content undefined. Upstream 0d564a2 clears them (sampled mid grey, storage 0); ported behind `NX2NAVI_DUMMY_CLEAR` (0104: 0 old, 1 upstream, 2 sampled magenta as a marker). The Hyrule Field rock shaders (fs 04f8a514, 11ed0dad, 1b4ff3c8, fa13d736) take their colour layers from **bindless 2D-array handles read from the material SSBO** (`fp_s0` = c0+0x510, 0x25ea76000; GLSL `fp_t2da_cb0_40000000[handle & 0xfffff]`); a dump's `fs tex slot` list shows only cb-bound slots, so those layers are invisible in passes.txt. The listed rock textures (3270/3272/3274, 2855-2862) are ordinary ASTC->BC1/BC3 (vk132 view 0x8b etc.) like ~50 other textures that render fine, and mirrored (so `TEX_REUSE`, GPU-only, does not touch them; `TEX_DESC_STRICT` acts on GPU slots only).
- **VRAM knobs and what they cost.** VMA keeps part-empty 256 MiB blocks (`NX2NAVI_VMA_BLOCK_MIB`, 0077), so driver usage does not fall when allocations are freed; on RADV plain images share those blocks.
  - `TEX_RT_DEDICATED_MIB` (0052, default 4): render targets of that size and up get their own memory, so freeing them frees VRAM.
  - `TEX_RT_TRIM` (0052/0065, default 95, 85 in `try-vram`): drop released RTs above that share of the budget. The game takes many RTs straight back, so a trim is judged 32 submits later and backs off (`_COOLDOWN`, `_AGE` 240, `_PER_MIN` 6). Without the backoff it churned 14 GB/min with no gain.
  - `TEX_RT_RECYCLE` (0075/0078, `build`/play13 only: gone on rebase-upstream, where upstream `TEX_REUSE` does this; code default 0; `just try-vram` sets 1): a new RT takes the image and memory of an idle released RT of the same description instead of allocating. This is the perf lever under streaming: off, released-RT churn (count sweep destroyed 34 GiB in 46k frames) costs about 30 fps in Hyrule; on, lab card use 84-94% vs 91-99%, worst frame 27 vs 98 ms. Risk: content lost when the game takes a recycled RT back (lighting flicker with camera/time of day, play11); 0078 skips taken-back and remade keys. With 0078, a full 46k-frame Hyrule replay (l12rt) ran clean: card 13758 of 14934 MiB at f45000 vs 14360 of 15330 on play11 (l11hold), released own memory 271 vs 1436 MiB.
  - `TEX_RELEASED_YIELD` (0039/0042): the released list gives memory back above a budget share; never fired on RADV with the card full because block slack hides the frees.
  - `TEX_LIVE_EVICT` (0072, default 85, `_IDLE` 3600 / 900 in `try-vram`, `_GUARD`): drops the longest-unbound mirrored, not GPU-written, live entries above the threshold; they return from storage on next bind. `TEX_LIVE_RT_IDLE` (0076) for live RTs: dropped 47 MiB in 46k frames, worse worst frame, not adopted. Live RTs are not idle.
  - The pressure valve `TEX_VRAM_PRESSURE` never drops RTs.
- **Where VRAM goes.** A fresh start holds about 5 GB of game textures in an area; a 90-minute session grew live sampled textures 3.5 -> 11.3 GiB (ASTC 5x5 0.7 -> 3.2, 4 GiB from stale slots of gone keys). Death Mountain: 11.6 GiB = 5.5 RTs (3.3 released), 2.0 ASTC as BC3, 1.0 mirrors; GTT 5.6 of which 4.85 shadow. `mem: heaps` / `mem: textures` lines every 1800 frames (0037, 0038) show driver, VMA, kernel and per-format figures. Driver/VMA/fdinfo agree: no hidden memory.
- **#160 offline reading of Cal's long logs (2026-11-12; `NX2navi/build/v111/logs/play-*.log`, `mem: vram by use` every 600 frames; all with `NX2NAVI_TEX_RELEASED_MB=3072`).** No unbounded growth on the 0.9.2 base: in use climbs for the first ~12,000 frames, then sits on a plateau. play46 (3fd125830045) `play-20261112-163836.log`, 99,600 frames, budget 14,878 MiB: in use 3,816 (f600) -> 10,839 (f12000) -> 11.9-13.6 GB to the end, peaks 14,999 (f83044); live textures 2.7 -> 4.4 GB by f12000, then 3.8-5.3 GB; released 0 -> 2.6 GB by f12000, then 2.9-3.2 GB with excursions to 5.1 (f53400) and 5.9 GB (f83044); mirrors 0.9-1.3 GB; outside VMA 0.5 -> 1.3 GB. play44 (026ec9fd5aa8) `play-20261112-151611.log`, 82,800 frames: flat at 6.9-7.3 GB (live 3.7, released 30-1,100 MiB), max 9.2 GB. play44 `play-20261112-154302.log`: flat 7.1 GB for 55,000 frames standing still (up 0 per window), then at f57600 an area change with 450 textures uploaded per 600 frames for 5,000+ frames: released 0.15 -> 3.0 GB, live 4.2 -> 5.1, in use 7.1 -> 11.4-12.8 GB. The "14 GB" is the in-use peak, not live textures. So the growth is the released list filling to its cap in a busy area plus mirrors and live textures of that area; areas do not accumulate across loads (play46 live textures fall back to 3.8 GB at f96600).
  - **Lab tour check (2026-11-15, slim2 701e7ce, dma-buf, 3 runs, `.lab/tour160.sh` = `tools/load-cell` with `TOUR=` 8 areas, GAP 1200, read by `tools/vram-tour`).** About 29 area loads over 4 rounds, then the warps stop firing in Market (f30357 on, standing). Live textures per round mean 3.8-4.3 GB in round 1 and 4.2-4.8 GB in rounds 2-4, peak 4.79-4.95 GB in every round of every run; released textures stay at the 3072 MiB cap (max 3.0-3.7 GB) while loads run and drain to 0.07-0.2 GB once they stop; in use 11.8-12.3 GB max, under the 80% line. No growth across areas: #160 closed. Warp entrance names land in nearby scenes (e.g. Market, Sacred Forest Meadow), which is fine for a tour. Long sessions still differ from this tour by real play (time of day, cutscenes); reopen with a play log if it comes back.
  - The VRAM pressure rule (80% of budget = 11.9 GB, aims 2% lower) does fire: `under VRAM pressure` drops 395 in one window of play46 (f54000); `idle live textures evicted` stayed 0 in every window of both logs. In use hovers at 12.1-12.6 GB because that is the rule's line (it counts `vk_mem_vram_live`, free space in VMA blocks excluded; "in use" counts it), so the card is never over budget in steady state; the 1.7 GB over is the excursions.
  - **Leak/retention found: the released cap is not a cap.** `drop_stale` (`vk_texture.c`, called from `sweep_pressure` when `rel_bytes > released_cap_bytes()`) skips entries not `comes_back_intact` in its first pass and in its second needs `stale_after` and `idle`. play44 `play-20261112-162732.log` held 7,392 released entries, 4,330 MiB (own memory 7,270; cap 3,072) from f12600 to f23400 (11,000 frames, `dropped past the size limit 0` all along) with nothing sampling them: GPU-written/dirty entries and entries a pool slot still names are neither intact nor idle. The excursions to 5-6 GB in play46 are the same: entries younger than STALE_FRAMES (120 presents) are never dropped, and an area change releases thousands at once. The cap is also only checked every 8 submits.
  - Proposed knob (not written): `NX2NAVI_TEX_RELEASED_HARD_MB` (default 0 = as now): above it, also drop released entries that do not come back intact once older than N presents (they come back empty, so it risks the black-frame cases listed under the released sweep; hence off by default), plus a log line of how many bytes the non-intact entries hold, so the retention is counted before anything is dropped. Lab test, when the GPU is free: a teleport loop through 5-6 areas (Hyrule Field, Castle Town market, Kakariko, Graveyard, Death Mountain Trail, Kokiri Forest; `tools/load-cell`/test-script teleports), 8 rounds, standing 30 s after each load, read `mem: vram by use` (released, live) after each load and the `perf:` released lines; pass = released <= cap + 10% after the 30 s stand and live textures back to the first-round level (rounds 2-8 within 5%), and no black frame. Compare knob off/on, 3 runs each. Standing-still windows only.
- **Camera-turn uploads in a grotto (2026-11-12, skysh 44398f8, Cal's `play-20261112-212219.log`, dump f77135 = recipe `tools/scenarios/grotto-pan.dbg`; CPU only, read from the perf lines, Cal walking and turning, so indicative).** "Textures uploaded" in the perf line counts new entries (`entry_of` -> `create_tex`, made at a lookup, the pool refresh's included), "re-uploaded" live entries whose storage pages were written (`make_fresh`). Frames 66,000-82,000 (Kakariko side, grotto), 266 windows of 60 frames split by the game's own file reads in the window (`work in the window` line): under 20 files: 366 made, 54 re-uploaded, 323 released entries dropped past the size cap (`NX2NAVI_TEX_RELEASED_MB=3072` from the run script; the released list sits at 3.07 GiB, ~5,000 entries), 66.6 fps; 300 or more files (170-340 MiB of zstd a second: the game streaming assets from disk as the view changes, logged as `scene: KokiriForest_Adult loads` / `KakarikoVillage...` at 76864/76884 though Link stays in the grotto): 821 made, 232 re-uploaded, 669 dropped, 49.7 fps, upload batches 2.3-2.9 ms of GPU a frame against 1.0. In Hyrule Field standing (frames 10,800-25,200) all three are 0. Made ~= dropped ~= `texture finalizes: slots marked` in every window. The one slow frame in Cal's spike (76875, 52 ms) is fence 25 ms + a 15 ms `pool init/finalize`, not texture work. The "filled from storage over a live entry" lines of that spike (696 in the session, capped per address) are new keys that differ from the live entry at the same storage only in `NVN_TEXTURE_FLAGS_IMAGE` (0x4) (ASTC as BC3 where the live one became BC1): two images and two decodes of the same bytes, but a few percent of what is made. Open: whether the baseline (game reading nothing, ~6 made a frame) is dropped keys coming back (cap thrash: the list holds ~12 s of releases at ~240 MiB/s dropped) or new descriptors; the log had no counter for it. Patch 0115 (exe `texchurn`, `NX2NAVI_TRACE=perf`, counts only) adds it: `perf: ... CPU-written textures made N: again after a drop of their key ... (past the size cap, under VRAM pressure, replaced at their address; within 2 s, 2-10 s, 10-60 s, later; taken back before the drop); never dropped: over a live entry that differs in flags only, over another live one, over a released one, alone` (`remade_note` in `drop_tex`, `remade_count` in `origin_made`: a 65,536-slot table of each key's newest drop, unlike the 4,096-entry drops ring, which held ~10 windows) and `released entries by kind` (intact and droppable by the cap, intact and not yet, overwritten, content only in the image). Lab cell: `tools/pan-cell <exe> <tag> 3 [KEY=VAL]` (grotto recipe, right stick held frames 2400-4200, Link standing; `tools/pan-sum` per window). Candidate if the cap is the lever: a larger `NX2NAVI_TEX_RELEASED_MB` (upstream's own default for this card is ~3.7 GiB, a quarter of the budget; the VRAM pressure rule at 80% still bounds the total: in use 12.3-12.7 of 15.0 GiB, of it 1.4-1.7 GiB free inside VMA blocks).
- **Streaming cost (#173).** Riding fast: `pool_fini` waits (1.6 s per 1800 frames), 49 ms pipeline-build spikes, 94k texture releases per 1800 frames.
  - **Recheck 2026-11-15 (build 701e7ce slim2, dma-buf, CPU-read of Cal's logs + 2 lab runs, indicative).** The play11 figures do not describe riding as such: in Cal's play49 log `play-20261112-195322.log` the `vk: replay queue` lines show `pool_fini` waits only in the 1800-frame blocks that hold area loads (f16200: HyruleCastle -> HyruleField_Adult x2 -> Market, 1484 calls, 205 waited 1.41 s; f18000 Death Mountain 1.45 s; f39600 FireTemple/GoronCity 1.81 s; field and standing blocks 0). Each wait is a full replay drain (`vk_be_pool_fini` -> `replay_drain(DR_POOL_FINI)`, `runtime/vk_backend.c:720`), ~1-7 ms each. `texture_release (queued)` runs ~47-89k per 1800 frames in every block, standing too, with 0 waits: not a cost. Lever candidate (not built): queue pool_fini on the replay thread instead of draining (needs the pool's memory kept until the replay passes it). Repro gap: a free camera flown 320 m over the field (`tools/scenarios/field-fly.dbg`, `.lab/epona/fly-cell`, LSTICK held) streams nothing (0 files, 0 textures/60 at 80 fps): the game streams around Link, not the camera, so a riding cell needs Link moving fast (no lab recipe for Epona yet).
  - **Area-load cell and POOL_FINI_DEFER A/B (2026-11-15, `tools/stream-cell` = stream-zora warp chain, frames 1260-5800, per-60-frame max interval from the perf lines via `.lab/epona/hsum.py`; dma-buf every run).** A/A slim2 701e7ce x6: 59.6/30.0/61.0/60.0/51.0/60.5 fps, worst frame 81-795 ms, 42-61 windows of 76 with a >25 ms frame, pool_fini 4,623-4,665 calls, 464-505 drains, 243-558 ms waited: two of six runs are outliers (700-800 ms hitches), so this cell needs >=3 runs and medians. Exe dpf1 (branch `dpf` 934a52d, .lab/wt-dpf; run.log says 701e7ce-dirty) adds `NX2NAVI_POOL_FINI_DEFER=1` (`vk_be_pool_fini` queues an `RI_POOL_FINI` replay item, `vk_pool_fini_key` runs it on the replay thread; `vk_be_pool_init` drains while one is queued). Interleaved x3: on 25.5/58.9/59.7 fps, worst 342/108/106 ms, >25 ms windows 69/58/49, pool_fini waits 0; off 58.7/59.8/59.6 fps, worst 119/112/110 ms, 57/57/62, waits 239-333 ms. The drains go away but the frames do not change: they were on loader threads, off the frame path (on1 like the A/A outliers). NO WIN, not in build. The area-load hitches (worst ~110 ms, ~5 frames >50 ms per run) come from elsewhere: next look at `program_release` drains (765 calls, 114 ms in the first 1800 frames) and the 49 ms pipeline builds.
  - **Hitch frames traced (2026-11-15, slim2 701e7ce, `stream-crit-1`, `NX2NAVI_CRIT=1200-3300 TRACE=perf,present,sched`, dma-buf, x1 = indicative; 59.0 fps, worst 113 ms, 5 windows >50 ms like the A/A).** Neither candidate is on the frame path: every `perf: slow frame` line (13 frames 50-159 ms) shows blocked pipeline 0.0 ms and drain 0.0 ms, and the 49 ms pipeline builds and `program_release` drains happen on other threads. `vk_be_program_release` (`runtime/vk_backend.c`) drains only to keep the `prog_t` and its code alive for queued replays (`find_stage` reads them); `vk_program_release` itself is a weak no-op here and upstream. The hitches are of two kinds. (a) Replay-bound: main (0x1003) sits in one host call, `nvnQueueSubmitCommands` (game main+0x646be0, NVN_BLOCKING) waiting for the async replay: f1010 159 ms (replay 153.7 ms, 8 device memory allocations 588 MiB, 325 file reads/zstd 285 ms on loaders), f2640 89 ms (replay 83.1, one 231 MiB allocation), f1078/f2038 (replay 34/28). (b) Game-side CPU: f2448 113 ms = guest worker 0x1050 running 68.8 ms (zstd decodes 83 ms on loaders) while main waits 39 ms in the submit; not ours to fix. crit_path per frame: main `host` 20-74 ms in every >40 ms frame. Next lever: what the replay thread does in (a), likely big device-memory allocations at an area change (render targets / pools allocated on the replay thread); trace them with a per-allocation timing line before building anything. Upstream e70cbb6 (pool destroys out of the completion callback and cmd_lock) cherry-picks cleanly onto build 0c4f210 (branch `hitch` in .lab/wt-hitch, not built, not measured: fence 0.0 in the slow frames, so it is not expected to move these); its follow-up c4140a3 conflicts (needs upstream's `vk_mem_collect_try`).
  - **Replay-bound hitch frames profiled (2026-11-15, slim2 701e7ce, `runtime-linux/prof_linux.c` replay thread, presents 900-3300, `tools/prof-window --frames N-N`; plus exe hitch1 = build 0c4f210 + a diagnostic pool_sync line, worktree .lab/wt-hitch, uncommitted).** Not device allocations: the replay's time in those frames is `bind_resources` -> `pool_sync` -> `pool_fill`/`pool_write` (`runtime/vk_exec_draw.c`), i.e. texture-pool refills and their `vkUpdateDescriptorSets` (RADV), with `bl_copy_rows` (block-linear detile, 44 ms in f2585) and `walk` self (f3056) in others. (1) The worst one, ~134 ms in a ~190 ms frame near f971 (before the 1260 window), is the pool's first sync (`pool_sync_entries`, `!PL.ready`): a stand-in into all 16 kinds x 40,960 slots x 8 ring sets with `PL.all`, 5,296,371 descriptor writes, while only kinds 0x40c are used. A one-time cost at the first draw that binds the pools; filling only the used kinds (and a kind's stand-ins when it first appears) would cut it to ~1/5 (not built). (2) In-window area loads: one sync refills 3,300-4,100 slots with ~10,500 writes in 23-40 ms (f2596, f3070), under the loading budget (`pool_create_ns`: `NX2NAVI_POOL_LOAD_MS` default 50, `POOL_LOAD_STEP` 128). A/B `NX2NAVI_POOL_LOAD_MS=12` vs default, stream-cell x3 interleaved (dma-buf every run): worst 134.7/135.7/97.3 vs 298.6/136.2/90.7 ms (median 134.7 vs 136.2), >50 ms windows 5/6/5 vs 9/6/4 (median 5 vs 6), fps 60.5/60.4/54.9 vs 55.7/60.7/57.3: no clear win, within the cell's spread.
  - **First pool sync fixed behind a knob (2026-11-15, patch 0127 ca12e5e, exe lazyk1 = 9b69085 + it, stream-cell x3 interleaved, dma-buf every run, window 780-5800 incl. the first sync, CPU load 2-8 from another agent's cargo: indicative).** `NX2NAVI_POOL_LAZY_KINDS=1` (`pool_standins` in `runtime/vk_exec_draw.c`): stand-ins as array runs, only kinds in `vk_pool_kinds_used` (set by `vk_pipeline.c` when a module is made, so before any draw can sample the kind), a new kind's in `pool_sync_entries` before its slots fill. First sync 135/161/179 ms (5.3M writes) -> 33/44/41 ms (1.04M writes, most of the rest is the ~7,000 real refills); worst window 182/519/291 -> 146/103/148 ms (median 291 -> 147); >50 ms windows 10/11/8 vs 10/11/7; fps 58.1/53.5/52.8 vs 54.9/55.3/56.4. The area-load refills (b) stay: 10-16k writes in 21-32 ms are lookups and texture creation in `pool_fill`, not the writes (2-3 us each), so batching writes would not move them. `bl_copy_rows` (`runtime/tex_deswizzle.c`) already copies 16-byte memcpys over `par_jobs` bands for levels >=1 MiB: no cheap win seen. `NX2NAVI_POOL_SLOW_MS=<ms>` logs every slower sync.

## 7. Shaders

- **What the game ships.** Compiled NVN 2 shader programs (Ampere SM86 code with an 0x880-byte control section and c1 constants), as data in RomFS and ExeFS (`tools/prepare_shaders.py:1-10`).
- **The translator.** `nx2navi_xlate` is the pinned Ryujinx shader translator 1.3.2 (`tools/vendor/ryujinx`) plus upstream's patches (34 of them, `tools/xlate/patches/`). Before translation, `AmpereLowering.cs` lowers SM86 to Maxwell, and `MeshSpirv.cs` handles mesh stages. It is built with .NET 10 NativeAOT and emits SPIR-V plus a JSON resource list. The runtime keeps a pool of `--serve` child processes (`runtime/gfx_shader.c:1-4`).
- **Cache key.** sha256 over:
  - the translator identity (hash of its sources, `nx2navi_xlate.id`; play log 21);
  - the code hash (stage, control section, code, c1);
  - the translator "answers" (bind state), masked to the slots the shader reads.

  Host capability answers are mixed in too (`gfx_shader.c:6-20, 318-320`).

- **Post-passes per pipeline.** `vk_pipeline.c:645-964` applies rebind, descriptor set, dual source, added outputs, fixups and pool rebind. A TXD gradient transpose exists but stays off for Switch 2 titles (`gfx_shader.c:797-806`).
- **Pipeline cache.** `pipeline-cache.bin` (play log 45). Our patch 0032 skips redundant exit saves.
- **Prewarm.** At boot, 44,195 shaders and 6,418 pipeline keys are prepared in about 1.4 s warm. The guest starts 4.9 s after process start (play log 48, 66, 69).
- **No graphics pipeline library here.** Because of `RADV_DEBUG=nogpl` (the RADV crash workaround), whole pipelines are built (play log 26-27, 34).
- **Skip/wait policy.** A draw whose pipeline is not ready:
  - is skipped if its targets were rendered last frame;
  - waits if it is a "one-shot" draw into never-rendered targets, up to `NX2NAVI_ONESHOT_WAIT_MS` (`runtime/vk_exec_draw.c:47-53, 3049-3080`);
  - waits within a 50 ms per-frame budget if it is a full-screen draw.

  `NX2NAVI_PIPE_SKIP=any` is our default.

- **Lowering bug class: bit positions.** `AmpereLowering.cs` re-encodes SM86 instructions as Maxwell; a field put at the wrong bit silently changes semantics. I2F carried the signed flag in bit 12 instead of 13, so every signed int-to-float converted as unsigned (Jabu floor/walls; fix 0064, check `tests/i2f_sign_check.py`). Suspect this class for geometry that is right in sign-free cases. A translator fix changes the translator id and re-keys the whole cache (`just try-i2f` uses its own `xlate-i2f/`, `shader-cache-i2f`, `pipeline-cache-i2f.bin`).
- **Checking the lowering: `just xdiff`** (patch 0085, `tests/xdiff/`). Runs real instructions of every form in the cache's stored inputs through an SM86 reference and their `--lower` output through a Maxwell reference that decodes with the translator's own `InstTable.cs`/`InstDecoders.cs` (`isa.py`), so a field at the wrong bit shows as a mismatch. A hand audit of the ALU/conversion lowerings (FADD FMUL FFMA FMNMX FSETP ISETP FSET SEL I2FP I2F F2I FRND IADD3 IMAD IMUL IMNMX LOP3 SHF SHL SHR ISCADD MOV, Maxwell side) found every field at the decoder's bit. Two hazards found on a transcription (`tests/xdiff/lower_py.py`), occurrence in the game unproven: `Lowerer.Plop3` writes its two destinations with two guarded ISETPs, so `@P1 PLOP3 P1, P3` evaluates the second under the new P1 (IADD3's carry writes are ordered for this, PLOP3's are not); `Lowerer.Imad` drops `~RZ` in .X mode (adds 0, not 0xffffffff). Uniform-datapath opcodes are their vector twin + 0x80 (AmpereLowering.cs UniformAlu), except UFLO 0x0bd, UBREV 0x0be and UPOPC 0x0bf, whose twins are FLO, BREV and POPC (0x100, 0x101, 0x109). The lowering handles those three separately (Uflo/Ubrev/Upopc, correct). The xdiff reference once applied + 0x80 to them and ran UBREV as F2FP, a false alarm fixed in 0086 (`sm86.py UNIFORM_TWIN`). Other facts: a lowered program starts with RUP (R238) = 0, so uniform predicates are false at entry; `F2I` with a destination size field (bits 75-76) of 0 (8 bit, if numbered as I2F's source sizes) lowers to a Maxwell IDstFmt the translator does not define (converted as unclamped U32, signedness lost); MUFU.SIN/COS take turns on SM86 and are multiplied by 2pi in f32 before the translator's radian SIN/COS, so arguments beyond a few dozen turns lose precision by design.
- **Invalid SPIR-V.** Mesa rejects some modules and RADV then dereferences NULL in `radv_shader_spirv_to_nir`. Known case: a layer-count size query (component 2 of `OpImageQuerySizeLod`) on a texture typed 2D by default (`tools/txq-array-fix.py`, patch 0050; guard 0033). Check suspects with `spirv-val`. Gone since translator xlate-play33 (e8d52df6, 2026-11-15 scan of `shader-cache-rebase`): 0 of 44,249 modules it made have the defect; the 205 left are 2026-11-08 files of older identities, never read again (the cache key holds the translator identity, `gfx_shader.c` top); 0 caught faults in Cal's sessions since 11-12 (#161 closed).
- **Window origin.** The upper-left origin and a y-flipped viewport put NDC +y at row 0 as NVN does, so front-face winding maps unchanged (`vk_pipeline.c` `vk_pipeline_set_dynamic`).
- **FMZ.** The game's SM86 shaders never set FMZ; the sky-SH NaN was a shadow-sync bug (0004), not 0*inf.

## 8. Timing

- **The game's own pacing.** Shipping Ocarina steps its update by whole vsync intervals. Above 60 fps, gameplay, the interface and the frame counter at update `+0xd58` all run fast (`recomp/patches-v111.txt:21-28`).
- **The `ostep` patch set** (`NX2NAVI_OCARINA_REALTIME`, on) rewrites two instructions at `main+0x6e6cc0`. The per-frame update then reads frames-per-update from patch page `+256`, which `frame_rate.c` writes each present as the display interval in 60 Hz frames (play log 39-41).
- **The other sets** (`fps60`, `realtime`, `cloth`, `bounce`) belong to upstream's other title's tables (`patches-v121.txt` etc.).
- **The frame limit** is `fps_limit` / `NX2NAVI_FPS_LIMIT`, capped at 240 (`frame_rate.c:21-23`). Cal's ini currently says 60 (play log 379); the perf trace ran at 240.
- **Game time follows wall time.** The step is the moving average of the last 5 display intervals, at least 1/240 s and at most 1/15 s (`frame_rate.c:10-13, 55-58`).
- **Why replays drift.** Recorded input is keyed to game time, and game time is the measured wall time. A different frame rate gives different steps and stick-sample instants, so positions diverge (tracker #145).
- **Fixed-step replay clock (2026-11-15, patch 0124, exe fstep ef9a7a8 on slim2 701e7ce).** `NX2NAVI_FIXED_STEP=<hz>` (default off) gives every present exactly 1/<hz> s of game time (`frame_step_present`, `world_clock`), and the scripted helpers (routes, free camera, capture replay state machine `bugcap_replay_tick`) read `frame_step_script_ns` (game time) instead of `plat_now_ns`. Guest time sources NOT on it: `rt_ticks` (`main.c`, nn::os GetSystemTick, NVN timestamps `nvn_ext.c`), nn::time clocks (`ov_system.c`), the audio device; and guest threads (loaders, streaming) are host-scheduled, so a load still lands on a different present per run. Capture A/A f2663 x3 (Cal's ini, memfd): ready present 2543/3270/3284 off vs 2199/2326/2457 on; Link ends at the same spot to 0.1 m on, 0.7 m apart off; fps 49.5/53.1/46.7 off vs 49.2/45.3/46.3 on (no collapse, indicative n=3); shots (NX2NAVI_SHOTS 3000-5400:600) byte-identical 0/5 both ways. Next for real determinism: virtual `rt_ticks`, and loads waited to completion before the window.
- **Stalls the frame-time split cannot see (2026-11-11, rebase-upstream 57e7476, nx2navi.play25).** The frame-time summary's categories time the replay/renderer only, so a worst frame with 0.0 everywhere (play22 f2928 297 ms, f505 296 ms; play-20261111-213952 f92 453 ms) was spent off the renderer. `NX2NAVI_STALL_MS=<ms>` (default 0; `kern_stall_frame` in `runtime/kernel.c`, called from `perf_present`) logs `stall:` lines for such presents: per busy guest thread (main first, up to 6) the kernel states over the interval (run/core/host/sleep/sync/cv/lock/addr, from `acct`, which then counts without `TRACE=sched`), host CPU and run-queue ms (`/proc/self/task/<tid>/schedstat`) and minor/major faults. Upstream 760a7aa (not in rebase-upstream) keeps freshly thawed regions thawed: a candidate for shadow-pool churn.
- **Area loads froze the game (2026-11-11, play26, rebase-upstream 7a35985, log play-20261111-223540).** Both big Hyrule Field stalls (f697 1516 ms, f2056 328 ms) are upstream 71eb5fb's pool load mode (`vk_exec_draw.c` `pool_loading`, `NX2NAVI_POOL_LOAD_BACKLOG`): the count budget goes to 1<<20 and `NX2NAVI_POOL_LOAD_MS` is only checked between refreshes (`spent` in `pool_sync_entries`), so the frame's first refresh made all 3,974 (839) textures in one replay frame (~0.33 ms each, GPU ASTC + staging). Main sat in `host` (a blocking host call, `kern_core_away`, 8 ms CPU of 1502) waiting on the replay; play13 (c7102bb) has no load mode and never showed it. Thread 0x1069 (p55) ran guest code (`run`, not `host`) all through: the game's own load worker, concurrent, not what main waits on. 0091 (`NX2NAVI_POOL_LOAD_STEP`, default 128, 0 = old) caps each refresh so the load spreads over frames. The `stall:` lines now add per thread its entry and longest host call (`exe+RVA` of `kern_core_away`'s caller, resolve with nx2navi.map, plus the game lr). The f1952 233 ms stall (main `addr`, 0x104e 104k faults) is a different cause, open.
- **Scene entry: where the load window's time goes (2026-11-12; play34p = play34 bcd6e8c + sampler, behaves as play32; cold load of the save in front of the Market; `runtime-linux/prof_linux.c` samples of the replay thread, `.lab/sl/prof1.txt`, flight thumbnails `.lab/sl/flight1`).** This replaces the earlier "load hold times load step" reading, which named the hold but not what filled it.
  1. _Load screen, ~190 presents at 60 fps._ The picture is black with the load icon. Loader threads read and decompress (zstd 0.5 s per 60 presents), write about 3.5 GiB into CPU-visible pools, and initialise and register the area's textures as they go (`nvnTextureInitialize` + `nvnTexturePoolRegisterTexture` in pairs, ~25 a present, 4,869 in all). The replay thread waits for the next submission 98.7% of that time. Nothing it could do is done: no draw of a title or load screen binds the texture pools, so `pool_sync` (`vk_exec_draw.c`) never runs (after a boot its first call ever is the area's first frame), and no submission binds the device address table, so the table's shadows are not synced (`vk_memory.c` `vk_mem_shadow_sync`).
  2. _The area's first frame, 812-834 ms on the replay thread_ (the "812 ms with 56 ms of texture" frame). Its first part's prologue runs the table sync over everything written since the title: **561 ms** = 310 ms in the write-watch query (`PAGEMAP_SCAN` finds and re-arms ~900,000 written pages: `snap_regions` -> `ww_query` -> `plat_mem_written`) + 247 ms `shadow_copy` of 3.5 GiB. Then the draws: 95 ms `pool_fill`/`pool_write` (every slot's stand-in for the newly used kinds, once per run), 55 ms textures (128, the load step), 44 ms `sbase_make` (base copies of pages the GPU writes, first time), the rest ordinary draws. The 21 device allocations (1.6 GiB) and the recorder's core claim seen in the log at that moment are not on this thread's path: no sample is in an allocation. The refresh finds 4,869 slots to make, which starts upstream's load mode (`pool_loading`) and with it `frame_hold` (`vk_backend.c`).
  3. _14-16 held frames, 1.4-1.9 s._ Replay busy 1.0 s: 570 ms making textures (`upload` 479: 160 opaque-block check for BC1 `astc_blocks_opaque_mt`, 125 block copies `tex_bl_copy`, 99 `amdgpu_bo_alloc` for staging blocks, 41 ASTC records; plus 76 `mem_readable`), 173 ms table sync (the loader still writes), 82 ms `vk_mem_mirror_begin`, the rest draws; 0.33 s it waits for the game (the game's own ~23 ms a frame). The game's main thread sits in `nvnQueueSubmitCommands` (frame bound) all through, so game time runs at 6-10 fps.
  4. _The hold ends_ (fewer than 64 slots left, or 2 s): one present 2.3-2.9 s after the last. The fade-in follows at 30-60 ms a frame while streaming goes on (~415 textures per 60 presents).
  What the player sees: the load icon freezes for 2.3-2.9 s and the load is that much longer. What `frame_hold` is for (upstream 71eb5fb): without it the area's first frames are shown with a quarter of the picture as black stand-ins (22 presented frames in upstream's test; they measured the whole load as one 345 ms frame on a 4090 with imported memory, where step 2's copies do not exist and step 3 is ~4x faster). It is not the cause of the lost time: with `POOL_LOAD_STEP=0` the same work is one 932 ms held frame after the 820 ms first frame.
  Why play13 (.lab/wt-play13 333f6b3, pre-rebase) has shorter gaps (from its log lines, not profiled): it has neither the table sync (its first frame copies only the pools the replay resolves: 733 MiB, 81 ms) nor the load mode: the textures (606 ms) spread over 4 shown frames of 0.18-0.48 s under the streaming budget, at the price of stand-ins in the first pictures.
  Upstream 0.9.0 (fbd4067) changes none of this: `frame_hold`, the load mode and the table sync are as in our base; e501ded only turns `ASTC_ARENA` and `ASTC_SCRATCH_KEEP` on (the 99 ms of staging allocations above).
- **Scene entry: the fix uses the load screen's idle replay time (0099, 0101; `nx2navi.play36`, rebase-upstream 977acc7).** `NX2NAVI_SHADOW_PRESYNC=1` (`vk_mem_shadow_sync`): the first prologue of a present runs the table's sync when the whole present before had no reader and at most 256 draws (`PRESYNC_DRAWS`: title, load, menu), so a load's writes are copied as they come, ~5 ms a present; an area's frames always have a reader, so nothing changes there. `NX2NAVI_POOL_IDLE_MS=8` (`vk_exec_pool_idle`, called from `vk_exec_record`): the first submission of a present whose previous present had no pool refresh looks up the slots whose token changed (entry + upload, 16 at a time until the ms are up; slots over unmapped storage again when `mem_map_gen` changes), ~2 ms a present; no descriptor is written, the first real refresh finds the entries. The walk keeps out while a pool's shadow buffer is being allocated and for the present after (`vk_mem_shadow_making`, `vk_memory.c` `shadow_pool`): with textures being made beside it, the loader's `vmaCreateBuffer` of a 160-288 MiB shadow took 120-450 ms instead of ~20 (inside `amdgpu_bo_alloc`; why the kernel is slower there is not known), which showed as one present 0.27-0.48 s late where a teleport's load starts. The area's first draw then finds a few hundred slots, under `POOL_LOAD_BACKLOG`: no load mode, no held present, and no stand-ins either, because the textures exist. What is left in the first frame (~210 ms cold): the one-time pool fill (80), base copies (86), a frame's worth of table sync. Both default off in code; `tools/load-cell` / `tools/load-stat` measure it. Measured 2026-11-12 in one session with `tools/load-cell` (cold = one boot, the save's own load; 3 runs a cell, load average under 6; mean (min..max) ms; "longest" = longest gap between two pictures, "lost" = time beyond 60 fps over the load's slow presents):

  | build | Market west: longest | lost | held | Graveyard: longest | lost | held |
  |---|---|---|---|---|---|---|
  | play13 (.lab/wt-play13 333f6b3, no build line) | 424 (390..443) | 1592 (1534..1676) | - | 1012 (720..1235) | 1512 (1270..1697) | - |
  | play32 (131d0f0-dirty = d9c9e0a) | 2339 (2312..2356) | 2674 (2635..2726) | 1547 | 1655 (1611..1688) | 1960 (1933..2003) | 1088 |
  | play36 977acc7, knobs off (1 run) | 2269 | 2613 | 1501 | 1650 | 1989 | 1093 |
  | play36 977acc7, `SHADOW_PRESYNC=1 POOL_IDLE_MS=8` | 216 (210..229) | 722 (674..767) | 0 | 178 (172..181) | 409 (382..437) | 0 |

  Teleports in one session (`NX2NAVI_DBG_TEST` warps Graveyard <-> field west, warm caches, one run a build): play32 holds 1-3 presents at each arrival, longest gap 291-551 ms (6 arrivals); play36 with the knobs has no present over 100 ms at any arrival (5), and the hitch where a load starts (the loader's pool allocations) is 122-136 ms against 91-120. Standing fps after the load (presents 1200-1500) is the same within the runs' spread (west 53.5 vs 53.8, Graveyard 60.0 vs 60.0). Flight thumbnails of the fade-in (`.lab/sl/flight-p36w`, `-p36g`, 320x180) show walls and ground textured from the first visible frame; the final pictures match play32's. Not profiled: play13's own 1.5 s (no sampler in that tree's exes).
- **Host-call sites of play27 stalls (2026-11-11, rebase-upstream 1d5b12f, log play-20261111-224513).** The `stall:` lines' `exe+RVA` is relative to the ELF's first LOAD (0x200000): resolve with `addr2line -f -e build/v111/nx2navi.<exe> <RVA+0x200000>`. Main's long host calls are all `nvnQueueSubmitCommands` (nvn_api_core.c NVN_BLOCKING, game main+0x646be0; 11 stalls, 1612 ms, max 736): it waits for the async replay. Loader threads (all entered through the nn::os trampoline sdk+0x16eb00) sit in `nvnMemoryPoolInitialize` (f2020: 0x1069 710 ms with 710 ms CPU, 0x1024 674 ms blocked behind it) and `nvnTextureWriteTexels` (427 ms, f669). In shadow mode a pool's init is `shadow_pool` (vk_memory.c): a host-visible VMA buffer of the whole pool plus a memcpy, so a big pool costs its allocation and clear. 0092 `NX2NAVI_SHADOW_RECYCLE_MB` (default 1024) reuses freed pools' shadow buffers of the same size and logs shadows over 20 ms with the buffer/copy split. Steady jitter is separate: 1299-1689 frames per minute over 25 ms, all `replay` (~33 ms avg), the play22-vs-play13 regression.
- **Steady replay cost, rebase vs play13 (2026-11-11, logs play-20261111-224513 = rebase 1d5b12f play27, play-20261111-214211 = play13 c7102bb; areas not matched, indicative).** Frames 600-1800 `mem: shadow` lines: rebase 3.34M pool syncs, 18.1 GB copied in, 7.26 s copy-in (replay thread, `vk_mem_shadow_sync`) + 1.83 GB written back of 5.48 GB seen in 5.46 s (completion thread, `shadow_write_back`, holding `shadow_lock` that the copy-ins need) = ~10.6 ms/frame; play13 652k syncs, 9.8 GB, 1.91 s = ~1.6 ms/frame. The sync count comes from upstream's device-address-table loop (`vk_mem_shadow_sync`: every table-reading guest submission walks all ~5000 shadows, ~460 not clean at 2 MiB region granularity), which GPU-driven foliage needs; play13 had no table sync. Copy-in ran ~2.5 GB/s with plain memcpy; play13 ran `SHADOW_NT=1` (0044, dropped). 0093 `NX2NAVI_SHADOW_NT` (default 1) restores streamed copies in `shadow_copy`. Write-back `merge_page` runs ~1 GB/s: next candidate.
- **0094 `NX2NAVI_SHADOW_TAB_FAST` (2026-11-11, rebase f742346, play30).** play29 (79bac9e, log play-20261111-230726): SHADOW_NT did not change copy-in speed (2.32M syncs, 10.7 GB, 4.46 s, ~2.4 GB/s); copy volume is near play13 (9.8 GB), so the extra cost is per-shadow work, not bytes. Copy-ins are already per-4 KiB-page dirty (`shadow_sync_pool` reads `cgen_chunk` stamps); only the clean test (`shadow_pool_clean`) is per 2 MiB region. 0094 adds `shadow_pool_pages_clean`: a table shadow failing the region test reads its own page stamps first and is skipped (sgen = gen_now) when none is newer. The `mem: shadow` line now ends with table syncs/ms and shadows clean by pages / synced. Unmeasured.
- **0095 `NX2NAVI_SHADOW_TAB_DIRTY` (2026-11-11, rebase 131d0f0, play31).** play30 (f742346, log play-20261111-231429) frames 600-1800: pool syncs 2.32M -> 1.05M, but table 1834 syncs 2938 ms (906k clean by pages, 559k synced); frames 0-600 had no table syncs and felt smooth. So the per-sync walk of all ~5000 table shadows is the cost. `vk_mem_shadow_sync` now keeps the table shadows indexed per snapshot region (`rsh`, `tregs`, `treg_gen`, `tab_index` from `shadow_table_add`/`shadow_forget`) and visits only regions stamped or untracked since the last table sync. The `mirror_sync` pass over the table still walks everything. Unmeasured.
- **Lab parity, rebase vs play13 (2026-11-12, `.lab/parity/`: run1.sh = lab-run + `--warp` + load-slot01 title load, batch.sh, tab.py = last full 60 s `frametime` window before the dump).** Standing and camera-pan windows: play13 (c7102bb, xlate 048a229e) vs play31 (131d0f0) / play32 (131d0f0 tree + 0096 d9c9e0a, xlate 53afad07) are at parity or better on the rebase (field-west 48.6/42.6 vs 51.9/47.6 fps/1% low, field-mid 51.5/44.0 vs 53.3/48.2, graveyard 60/52.6 both, pan 50.4/43.0 vs 50.0/43.0; >25 ms 0-5/min both). The rebase renders field/graveyard grass, play13 does not. Under `NX2NAVI_TRACE=perf` the `mem: shadow` line is per 60 frames, not 600: rebase spends ~3.3 ms/frame copy-in + ~4.5 ms write-back (completion thread, `shadow_write_back` merge, 100 of 260 MiB seen per 60 frames) + ~2 table syncs/frame at ~1 ms (about 290 shadows synced each; region queries only ~0.25 ms/60 frames, so 0096 changes nothing measurable); play13 ~2 ms/frame in all. Those run off the critical path in standing scenes. The rebase's worse numbers are in the load minute only (one 2.9 s present at scene entry vs several 0.3-0.7 s on play13; frames after 1500 have fewer >25 ms on the rebase). Running in a square through the field (load-run.txt, drifts): minutes 2-4 play13 44.2/41.1/41.5 fps, 1% low 27-33, 527-746 frames >25 ms/min; play32 41.0/42.2/43.7, 28-35, 517-619: parity. Pan A/B on play31: `SHADOW_WB_REARM=0` 48.6/40.4, 12 >25 ms; `SHADOW_BULK_WRITE=0` 49.2/41.2, 8; `SHADOW_TAB_DIRTY=0` field-west 49.7/45.5, 5 (vs 51.7/47.1, 2): all three earn their default. Lab runs are nice 19, pinned 0-7,16-23, ~50 fps in the field for both: indicative.

- **Live "rebase stutter" with shadow flicker, play44 (2026-11-12, CPU only, Cal's log `play-20261112-150102.log`, exe nx2navi.play44 026ec9fd5aa8, xlate-play33).** Verified from the log: minute 1 54.4 fps, 169 frames >25 ms (replay 95 at 32.6 ms, unattributed 70 at 49.4 ms); minutes 2-4 settle to 11-24 >25 ms, all `replay` (27-30 ms). Shadow storage per 600 frames: f0-600 322k pool syncs, 4.6 GiB copied in, 2.93 s, table 598 syncs 2.83 s (4.7 ms each, one per frame); f600-1800 655k syncs, 6.4 GiB, 2.46 s, table 1199 syncs 2.26 s, 5.2 GiB copied "ahead of a reader". Cal's play13-era logs (0.5.0, `play-20261110-225531/212647.log`) show 4.6k pool syncs, 1.2-1.4 GiB, 0.21-0.22 s per 600 frames: the rebase shadow table does ~70x the syncs and ~12x the CPU time. AO reruns (`EVO_ASYNC`) are a flat 6 per frame, so not the periodic part. Scene-entry stalls f1777/f1789 (233/591 ms) are the loader threads in one host call at exe+0x117fe4fb (section 8 scene entry). NOT verifiable from this log: whether slow frames are periodic and land on the frame that renders the game's shadow map; the play log has only 600-frame aggregates. Hypothesis: the per-frame table sync copies in the shadow-map pass's constants/caster buffers and, under `REPLAY_ASYNC=1` (event order off), the replay of that pass sometimes reads a pool synced a frame late, so the stutter frame and the shadow flicker coincide. Lab check: recipe at Cal's mark, `NX2NAVI_TRACE=perf NX2NAVI_FLIGHT=1 NX2NAVI_CRIT=1` per-frame series, then A/B `NX2NAVI_REPLAY_WORKERS=0`, `NX2NAVI_REPLAY_ASYNC=0`, and the table sync off the shadow-map frame.

  Update (same day, `play-20261112-150554.log`, play44 + `NX2NAVI_REPLAY_WORKERS=0`): Cal says the stutter is the same and comes while moving. Running forward, polygons at the bottom of the screen behind Link disappear and come back. Minute 1: 98 frames >25 ms (replay 28 at 42.6 ms, unattributed 65). f600-1800: 1.04M pool syncs, 8.4 GiB, 4.54 s; table 1863 syncs 3.64 s, 185k dirty regions (2.5x the 150102 run). Workers are ruled out. Note that "ahead of a reader" on the shadow line counts the syncs `NX2NAVI_SHADOW_PRESYNC` makes after a present that drew little (`vk_memory.c` ~2937). It is not a staleness count. Leading hypothesis (unverified): the game's GPU-driven mesh draws (indirect mesh tasks, `vk_exec_draw.c` ~5797/5898, knobs `NX2NAVI_MESH`, `NX2NAVI_MESH_AHEAD`). play13 drew none of them (all counts 0, the grass bug), and every rebase build draws them. That fits "since the first rebase, never in play13", the near-camera pop-in (ground foliage/terrain patches culled by last frame's data), and the extra pool syncs while moving (their instance and culling buffers stream in). A/B: same moving route, `NX2NAVI_MESH=0` vs default, then `NX2NAVI_MESH_AHEAD=0`.
  Mark burst-2808 (`play-20261112-151038.log`, play44, TRACE=perf, Gerudo Training Ground area, running; frames 2688-2808, 120 before the mark). `tools/burst-scan` finds nothing because it compares whole-frame luma. A neighbour diff (`tools/burst-backstep.py`, mean abs luma diff of frame N vs N-1, N+1 and of N-1 vs N+1, per third of the picture) finds back-steps. Verified: in about 16 places, frame N-1 is nearly identical to N+1 (top third 0.1-0.2 vs 1.8-2.1 normal motion) and N to N+2: the pictures go A B A B, so one present shows an older picture again. Pairs at 2704/05, 2709, 2721, 2728/29, 2737, 2740, 2744/45, 2752/53, 2763, 2768, 2775, 2784/85, 2794, 2800, 2807: every 4-11 frames while running. Under motion a repeated older picture moves the ground near the camera back and forth, which matches "polygons behind Link disappear and come back" and reads as stutter. The 60-frame perf lines (f2700: interval avg 20.5 max 27.2 ms; shadow 75k syncs 274 ms; terrain heightmap finalize 1) cannot place it per frame. Next to check (unverified): the burst ring captures the presented image or the replay's output in present order (`NX2NAVI_MARK_RING` source). If it is the presented image, the cause is in presentation (mailbox swapchain, `vk_present = mailbox`, or async replay handing over an older frame), not the shadow table.
  Verified: the burst ring is blitted from the presented image (`boot.c` ~342, `gfx_present.c`), so the back-steps are what Cal sees. `NX2NAVI_MESH=0` (`play-20261112-151252.log`) keeps the stutter, which rules out mesh draws. Cal says it is view-dependent (worse facing one way, and on play22 facing Gerudo from the Market entrance). The play logs carry no per-frame heading, so view vs. cost is not verified. `tools/perf-window-corr.py` over the 60-frame perf windows of 151252 (f>=1200, 43 windows): the frame interval correlates with write-watch MiB/ms (0.85/0.79), shadow ms (0.73) and GPU ms (0.62), not with binding checks. But the spread is small (16.5 vs 17.1 ms), so this is indicative only. The 151038 windows are dominated by area loads.
  Refined (`tools/burst-where.py`, burst-2808, mean abs luma diff on a 4x3 grid of frame N-1 vs N+1 at back-steps): the outer cells (world) differ by only 0.1-0.4, but the two centre columns of the middle and bottom rows (Link and the ground under him) differ by 0.9-3.0. So the back-step frame is not a re-presented old image. It is a new frame whose world/camera matches two frames earlier while Link is current. Hypothesis (unverified): a frame-late camera/view constant buffer, or the world draws' data, read from a shadow pool before that frame's sync, while Link's skinning data is fresh. Link's self-shadow flicker would follow from the light-space or shadow-map constants coming from the same stale buffer. This points back at shadow storage (table/pool sync order under `REPLAY_ASYNC=1`), not at the swapchain. A/B: `NX2NAVI_REPLAY_ASYNC=0`, then `vk_present` fifo; count back-steps with `tools/burst-backstep.py`.
  CAUSE (2026-11-12). Verified: `NX2NAVI_REPLAY_ASYNC=0` on play44 removes the back-steps (burst-1384: 0 of 119 frames while running, vs 20 in burst-2808). The perf line's "waits a CPU signal met only after the submission's copies were taken" adds up to 493 (async, mesh on) and 212 (async, mesh off) over the sessions, and 0 with the replay in step. Mechanism, from the code: Ocarina's main queue begins with a wait for an event the game signals from the CPU once it has written the frame's data, 1-2 ms after the submit call (`vk_exec.c` "the gate", `vk_exec_xfer.c` "events the CPU signals"). Synchronous replay waits for that signal before its copies (`vk_exec_gate_wait`, `NX2NAVI_GATE_WAIT_MS`) and holds a submission whose signal came late (event order). Under async replay both are off (`evo_enabled` returns 0 when `gfx_replay_async`). The uniform snapshot is also taken in the game's submit call (`vk_backend.c` `vk_be_submit` -> `vk_usnap_take`), before the signal, so the frame's camera and scene blocks hold the values of two frames back (the game alternates two). Upstream knows: 0533b30 (0.9.2) turned async replay off by default because it "can show a dark or flickering frame now and then". It is not caused by our shadow patches (0088-0101): `REPLAY_ASYNC=0` fixes it with all of them on. Fix 0109 `NX2NAVI_ASYNC_GATE=1` (play45): with async replay, the submit call runs the gate before `vk_usnap_take`, and the replay stays on its own thread. Lab 2026-11-15 (slim2 701e7ce, dma-buf, field-running, REPLAY_ASYNC=1, x3 each arm, moving so indicative): the perf counter "waits a CPU signal met only after the submission's copies were taken" sums 372/379/428 per run with the gate off and 0/0/0 with it on (gate waits 0.09-0.31 ms avg, 0 timeouts); fps 52.5/69.9/72.4 off vs 64.4/71.7/71.9 on, no difference beyond spread. Default stays 0 (UNCERTAIN.md).
- **Running stutter: what the replay does more while Link runs (2026-11-12, CPU only, logs of the load-run replays `.lab/pr-p32-srun`, `pr-p32b-srun`, `pr-p32-run` = play32 d9c9e0a and `pr-p33*-srun` = play33 b31135a, 0.9.0 base; per 60-frame `perf`/`mem` lines from frame 1300, windows split by textures made: "moving" >150 a window, "still" 0; `.lab/rs/win.py`; indicative: the replay drifts and no sampler ran).** Every moving window makes 300-450 textures (the streaming count, ~7 a frame, used up every frame) and the released list sits at its limit (`vk_texture.c` `RELEASED_MAX` 2048, `sweep_released`): 270-415 entries dropped per window, none still. Per frame, still -> moving (play33 srun; the other runs agree in direction):

  | per frame | still | moving |
  |---|---|---|
  | replay avg ms | 19.2 | 24.7 |
  | frames >25 ms per 60 | 8 | 46 |
  | write-watch queries / MiB queried / ms (all consumers) | 321 / 1,199 / 2.7 | 690 / 3,078 / 5.5 |
  | shadow sync ms (`vk_mem_shadow_sync`), of it the table's | 3.7, 2.6 | 5.9, 4.9 |
  | mirror tracking ms (`mem: mirror` tracking cpu, pre-snap queries) | 1.4 | 2.2 |
  | released entries dropped / textures made per 60 | 0 / 0 | 385 / 406 |

  Reading: the write-watch volume doubles because the loaders' streaming writes thaw frozen regions (`memory.c` `thaw_locked`: a write within `FRZ_QUICK_MS` of the freeze makes the region hot, held thawed 4 s doubling to 600 s; 63 of 65 thaws a window were such holds), and an unfrozen region is queried once per guest submission (6 a frame, `snap_regions` epoch = submission). The table sync's extra time is the copy-in of the loaders' bytes (1,191 vs 743 MiB a window). Together ~+4.5 ms of the +5.5 ms; texture making is the rest (render-thread texture block 2-3%). Whether the textures made are dropped released entries coming back is not logged (no counter for a released entry taken back): 0103 `NX2NAVI_TEX_RELEASED_MAX` (`released_max`, default 2048; `vram` = upstream ee46a19) is the cheap test. Replay workers: `REPLAY_WORKERS=4` on play33 was worse (894-1177 >25 ms a minute); upstream turned 3 on by default after 0.9.0 (432b4e4, +22% standing on a 5800X3D) together with 7eee481 (uniform snapshot copy split over the workers) and 9fe3dd3/a0a7548 (workers stop waiting for each other at queries), none of which play33 has, so that result does not carry over to upstream main. Next cells: `.lab/rs/cell.sh` with the recipe `tools/scenarios/field-run-route.dbg` (upstream `routeto` loop, same path every run), plain vs `NX2NAVI_TEX_RELEASED_MAX=vram`, and one run with `NX2NAVI_PROFILE` over the moving frames to split the +5.5 ms by function.

## 9. Input, audio, HDR and scaling, saves

- **Input.** SDL3 gamepads; the pad pressed last is the game's pad (`input.c`). Our patch 0014 prefers Steam Input's virtual pad. Motion can come from a second pad (patch 0034). The six-axis sensor and rumble are served through the hid overrides (play log 357-364).
- **Audio.** The game's `nn::atk` runs as lifted code and talks to `audren:u` over in-process IPC. `audren.c` and `audio_mixer.c` mix on the host and output through SDL (play log 333-336). Open problem #128: intro narration voices start faster at higher frame rates.
- **HDR, upscaling, frame generation.** HDR10 native swapchain (`vk_hdr.c`; play log 52-53). The game's tensor-core upscaler is replaced by decode-and-scale (`vk_tonemap.c`). FSR 1 runs when the window is larger than the picture (`vk_fsr.c`). FSR 3.1 and DLSS paths exist (`vk_ffx.cpp`, `vk_dlaa.c`, `vk_dlssg.c`), but FSR 3.1 is missing on this host (play log 32-33) unless a local ffx-api .so is built (patch 0112 NX2NAVI_FFX_LIB dlopens libamd_fidelityfx_vk.so beside the exe; the community port ychwch/FidelityFX-SDK-Linux, AMD MIT licence, builds the 1.1.4 VK backend, and its tree already holds the ffx-api sources (ffx-api/src) that a small Linux shim .so can compile for the FSR3 upscaler provider; recipe .lab/ffx-linux/{build.sh,shim.sh,shim/}, local only; the backend needs a stub for ffxSetFrameGenerationConfigToSwapchainVK; upscaler dispatch unverified on GPU). Frame generation needs AMD's frame interpolation swapchain (vk_fg.cpp is built around it), which the port excludes: it would have to be rewritten. Frame generation is off in Cal's ini; whether it works on Linux is not established.
- **Saves.** A host save directory with a working copy; the game's `Commit` writes it (play log 339-342, 493). `just play` copies saves into each recording bundle.
- **Scenes, entrances, save layout (teleport, 2026-11-11).** Scenes are named strings, not ids: each is `Banc/<group>/<scene>_{Static,Dynamic}.bcett.byml.zs` in RomFS (80 scenes; `_Child`/`_Adult` variants are separate scenes). The entrance table is `Banc/BancBasedResource/StartPos.byml.zs` (BYML v7, little endian; scene -> start-position name -> `Trans` xyz, `Rot` XYZ radians; 415 entries). `tools/scenes-gen` writes both into `~/claude/nx2navi/tools/scenes.toml`. `progress.sav` (per slot) is magic `04030201` then (u32 hash, u32 value) pairs from 0x28; hashes are murmur3_32 of GameData names (`GameData/GameDataList.Product.110.byml.zs` is BYML big endian and holds hashes only; names recovered by hashing executable strings, `tools/mm3.py`). String64/Vector3 values are offsets into the file. Current scene = key 0x1d6189da (String64); Link's position = `Player_Pos_For_Map` plus 0x960ad56a, 0xc884818d, 0x8773f02d (Vector3); yaw (degrees) = `Player_Rot_For_Map` and 0xa4aee8cd; age = `Sequence_IsChildhood`. `tools/warp-save` edits those in a profile copy; `lab-run --warp '<spec>'` does it for a run. The game's in-memory scene-change path (`SeqOneShotChangeScene`, `WarpMgr`, `NextSceneNameHash` in main's strings) is not traced yet, so there is no live warp in `build`. Upstream origin/main (fe3126e, 4e3280c, not yet in `build`) has one: `dbg_warp(area, pos)` in `runtime/debug_tools.c` reserves the next area and start position and asks the game's `Sequence_ControlInEvent = ChangeBancOnEvent` sequence, reading the same StartPos file; test runs reach it with `NX2NAVI_DBG_TEST="<tick>:warp <area> [<start position>]"`. After the rebase, prefer it; warp-save stays for cold starts from an edited save (unverified in game).

- Menu settings (runtime/ui/option_rows.cpp apply): a row's change goes into memory at once (cfg_set, cfg_version bumps) and
  consumers that re-read cfg follow; nx2navi.ini is written by opt_save_tick 0.4 s later, or only by the Save button with
  `NX2NAVI_MENU_LIVE=1` (patch 0080). Which rows are live: cfg.c metas `LIVE`, plus `LIVE_WITH_MENU_LIVE` under that knob
  (cfg_live); the rest are read once at start and show "after restart". Shadow range is live-capable because the cascade
  patch set loads its distances from the patch page (+64) on each call; render targets, shadow map sizes, swapchain
  features, the game's language/operation mode and RomFS-served packs are fixed at boot.

## 10. Our private patches

All are in `~/claude/nx2navi/patches/`, as local commits on `build`. Status comes from `~/claude/nx2navi/README.md`.

**Upstream rebase 2026-11-11** (branch `rebase-upstream` in `.lab/wt-rebase`, 591 upstream commits on; table and
proof per patch in `REBASE-2026-11-11.md`; becomes `build` once moved). 48 of our 85 commits stay (most adapted), 37
are dropped because upstream now does the same natively:
- Shadow storage is rewritten (`f740e95`): copy-ins and write-backs merge byte-wise against per-page base copies
  (`vk_memory.c merge_page`, `sbase_*`), copy-ins read the guest submission's write-watch snapshots (`snap_regions`,
  each 2 MiB region once). Our 0001/0004/0008/0010/0025/0044/0054 (page compare, spend list, diff threads,
  `SHADOW_NT`/`_GAP_KIB`/`_REWRITE`) are gone with the code they tuned.
- Event order across queues is native (`3aa8ff5`, vk_exec.c "event order across the game's queues"): a submission
  stops at a wait reached before its signal. `EVENT_WAITS` (0013/0016) and `AO_ORDER` (0046) are obsolete only with the replay on the
  submitting thread: `evo_enabled()` turns event order off under `NX2NAVI_REPLAY_ASYNC=1` (the justfile default), so
  play22+ replay worker-queue waits in submission order again (AO and character lighting read last frame: flicker,
  dump f17378 play24 e1fbd67). `AO_ORDER` no longer exists in the code (dead knob in run scripts); 0090 `NX2NAVI_EVO_ASYNC` (default 1) brings
  its occlusion rerun back for the async replay. `NX2NAVI_AO=0` matched only the old occlusion hash 561cf523 (rebase
  translator: 59867f7d) until 0090.
- The finish wait is upstream's `exec_wait` (`9728424`): it ends at the GPU's passes, not the write-backs
  (`NX2NAVI_WB_SPLIT=0` gives the fence wait). `GPU_WAIT` (0024) and `FINISH_DEFER` (0036) are obsolete.
- Texture memory: `NX2NAVI_TEX_RELEASED_MB` (`29d8451`) is our `TEX_RELEASED_MIB` renamed; `NX2NAVI_VMA_BLOCK_MB`
  (`8e656b8`, default 64) is our `VMA_BLOCK_MIB`; images of 32 MiB and more get dedicated memory (`fbb6783`
  DEDICATED_MIN); `NX2NAVI_TEX_REUSE` (`0101a87`, default on) reuses released GPU-only images, which replaces
  `TEX_RT_RECYCLE`; `NX2NAVI_TEX_EVICT` (`63bcb44`) evicts idle live textures that come back intact;
  `TEX_VRAM_PRESSURE` (default 80 now) drops released ones; released render targets are kept up to a hard limit
  (`c51ac7c`). Obsolete knobs: `TEX_RT_DEDICATED_MIB`, `TEX_RT_TRIM*`, `TEX_RT_RECYCLE`, `TEX_RELEASED_YIELD`,
  `TEX_RELEASED_LRU`, `TEX_DEDUPE`, `TEX_LIVE_EVICT`/`_IDLE`/`_GUARD`, `TEX_LIVE_RT_IDLE`, `TEX_STATE_GEN`,
  `TEX_CHECK_SKIP`, `POOL_KH` (upstream's `PoolSlot` keeps kh/kreg), the `TRACE=tex` line (upstream's texture
  origins and `texup` lines under `TRACE=perf`).
- Slots: a finalize marks only its own texture object's slots and the flag survives eviction (`ae0c814`, `25e3181`):
  the #149/#169 terrain holes are fixed upstream, so `TEX_STALE_LIVE` (0074) and `TEX_STALE_GONE` (0066/0068/0069)
  are gone. `TEX_DESC_STRICT` (0079) stays, placed before upstream's superseded/finalized branches of `slot_resolve`.
- Translator: I2F's signed flag in bit 13 is upstream's `837a82a` (0064 dropped; our `tests/i2f_sign_check.py`
  passes on the new translator). Upstream has its own translator patches 0036-0040, so our texel fetch clamp is
  `tools/xlate/patches/0041-texel-fetch-clamp.patch` there and `build_xlate.py` expects 40. The translator identity
  changes (53afad07... on the rebased tree), so every shader cache key changes. Upstream's *carry* (gfx_shader.c,
  `identities.txt` in the cache folder) uses the translations of previous identities until a shader is translated
  again; an old cache needs the old base identity (`nx2navi_xlate.id`) listed there to be carried.
- Linux platform: upstream's `platform/linux.c` now has its own `plat_frame_capture` (libgcc unwinder), its own
  `PlatJmp` with `plat_jmp_save/go` in assembly, and an aligned `plat_fiber_entry` (`e9edd6a`). `build-linux.py`
  therefore leaves out `runtime-linux/frames.c` and its per-file defines when the checkout's linux.c has no
  "not on Linux yet" stub: frames.c's 80-byte NxFrame would overrun upstream's 72-byte PlatJmp.
- Also native now: mesh draws in dumps (vk_dump_draw's `mesh` argument, `mesh_prims.txt`), `NX2NAVI_DUMP_FILE`
  (a dump.req-like file, a frame count in it), the Insert dump key, `NX2NAVI_ONESHOT_WAIT_MS` (same name, `fe3cca7`),
  the mesh c0 clamp (`00f06e6`), the census of texture memory by kind and format (`3c0a4d7`), the pipeline cache
  written only when it grew (`719ee94`), the per-heap `mem: heaps` line (TRACE=perf; ours adds the 1800-frame cadence
  and a `mem: kernel` fdinfo line), pool freshness by entry list (`4a954a1` POOL_FAST), the debug menu on F9 with
  `debug_menu = 1` (F9 marks only while it is off).
- Trace bits moved: upstream took 512 for `coop`, so `counters` is 1024 and `nvn` 2048.
- Rebase 3 (2026-11-12, branch `rebase3`, `.lab/wt-rebase3`, exe play41): play38's stack onto origin/main 322d7c0.
  Upstream moved the replay's per-recording state into `DrawCtx` (`85af8a8`; `ex->dc->c0_binst`, `cx->PM` with our
  pipeline-memo epoch `PM.ep`), split the walk's ops into `op_one` (vk_exec.c; 0090's `signal_seen` runs after it),
  copies the uniform snapshot on the replay workers (`7eee481`; 0012's unjitter runs between `copy_some` and
  `copy_down` in `vk_usnap.c copy_regions`), clears the stand-ins itself (`0d564a2`, so 0104 is left out), refuses a
  slot following a texture of another size (`ca75294 follow_size_ok`; 0079 TEX_DESC_STRICT still covers format) and
  sizes `NX2NAVI_TEX_RELEASED_MAX` by VRAM (`ee46a19 released_max`, so 0103 is moot). Replay workers default 3.

**Memory / shadow**

- 0001: write back only pages the GPU changed. On.
- 0004: shadow sync takes the CPU's bytes under the next part's GPU writes (sky-SH fix). On.
- 0008: page compare outside `shadow_lock`. On.
- 0010: neighbouring-pool write-watch queries. On.
- 0025: write-back compare on threads (`NX2NAVI_DIFF_THREADS`, 4). On.
- 0034-mem, 0035-mem: SetHeapSize / MapPhysicalMemory logging. On (logs only).

**Textures**

- 0009: compact freshness arrays. On.
- 0019: `TEX_RELEASED_MIB`, 3072 in `just play`. On.
- 0027: tex trace. Debug.
- 0028: `TEX_DEDUPE` / `TEX_RELEASED_LRU`. Off (dedupe paints wrong terrain).
- 0030: `TEX_STATE_GEN` / `TEX_CHECK_SKIP`. Off (no gain).

**Sync / replay**

- 0013, 0016: `NX2NAVI_EVENT_WAITS`. Off.
- 0024: `NX2NAVI_GPU_WAIT`. Default 0 (=1 is suspected of causing the horizon bands).
- 0036: `NX2NAVI_FINISH_DEFER`. Off (no gain).

**Draw / pipeline**

- 0006: clamp the mesh-stage c0 table. On (fixes the upstream overflow).
- 0018: RGBX/sRGB/BGRX vertex formats. On.
- 0012: `NX2NAVI_UNJITTER`. Auto.
- 0033-oneshot: `ONESHOT_WAIT_MS`, 30000. On (unchanged default).
- 0032: skip redundant pipeline cache saves. In `nx2navi.crash`, not swapped.
- 0033-guard: driver-fault guard around pipeline creation. In `nx2navi.crash`, not swapped. The fault it catches most (2026-11-10) is Mesa rejecting invalid
  SPIR-V: a layer-count size query on a texture typed 2D by default (README, patch 0050 and `tools/txq-array-fix.py`).

**Shaders**

- 0002: xlate honours fmz. Private translator build only.
- 0003: shader hot reload. Debug.

**Crash**

- 0031: Linux crash context. Not swapped.

**Input**

- 0014: Steam Input pad. On.
- 0034-input: `NX2NAVI_MOTION_PAD`, auto. On.
- 0051-input: `NX2NAVI_MOTION_SOCK`, auto (yakin socket, only without gamepad sensors). In `nx2navi.motion` only.

**Debug and tooling**

- 0005 (`NX2NAVI_WATCH`), 0007 (shot crop), 0011 (`DUMP_REQ`), 0015 (mark this moment), 0017 (`DUMP_DRAWS`), 0020 (`OQ_FORCE`).
- 0022 (counters), 0023 (Tracy), 0026 (`NX2NAVI_RDOC`), 0035-nvn (`TRACE=nvn`).

Open problems mapped onto the architecture:

- **#132 performance.** The game thread is the critical path (finish wait plus 17.8 ms unzoned). Then the completion thread's compares and the replay's shadow sync and pool refresh (section 5).
- **#146 AO flicker.** Replay ordering: the occlusion compute waits on an event the async replay used to ignore, so AO read last frame's half-res depth and trailed one frame behind motion. On `build` (701e7ce) the fix is 0090 `NX2NAVI_EVO_ASYNC`, default 1 (vk_exec.c "ambient occlusion after its event": reruns the occlusion after its event under `REPLAY_ASYNC=1`); `AO_ORDER` and `EVENT_WAITS` no longer exist in the runtime (UNCERTAIN.md corrected 2026-11-15). `NX2NAVI_AO=0` turns AO off.
- **#141 device loss.** Cal's play logs since 2026-11-09 and lab run.logs since 2026-11-12 hold no lost device; the last two (2026-11-08 pass marks, 2026-11-09 GPUVM read fault 0xffff80078f7fa000) were on old builds. The RADV `spirv_to_nir` fault (libvulkan_radeon.so+0x19be92) is caught (0031/0033). Upstream 8df4311, 1f4818f, 68bc197 (lost-device reports: timelines, mesh draws per mark, present fence waits) are not on `build` yet: take them with the next rebase before chasing the next loss.
- **#149/#169 missing terrain.** Two causes. (1) Stale rule on re-initialised height tiles, fixed upstream by finalize-own-slots (ae0c814, on `build`). (2) Texture pool length: Ocarina's pool has 33068 descriptors; the translator clamps pool handles to `TexturePoolLength`, which upstream 2388f1f (2026-11-12, on `build`, tools/xlate/Program.cs + vk.h `VK_POOL_TEX` 40960) raised from 32768. Every translator we play with (`build/v111/xlate-rebase` 2026-11-11, `xlate-play33`) predates it, so textures registered from slot 32768 up draw with slot 32767's image (ground see-through after an area load until it is reloaded). The shader cache keys translations by translator identity, so a new translator recompiles; upstream 46c764a/b04e7c8 are carried as patch 0126 (9b69085): b04e7c8's log (gfx_shader.c `pool_short_note`, vk_texture.c `vk_texture_register`) is always on, 46c764a's refusal (`carry_usable`) sits behind `NX2NAVI_SHADER_CARRY_POOL=1` (default 0). Without that knob, switching translators keeps the old 32768-pool translations through the carry (gfx_shader.c "Carry"): lab 2026-11-15 refused 80-326 of them per session. Lab (exe xl149, Graveyard<->Field west loads x3, dma-buf): old translator xlate-play33 logs `texture slot 32768 registered while 244-266 shaders ... index the texture pool with the earlier length` in every run, so Ocarina does register 32768+ in these loads; xlate-701e7ce + knob logs nothing. Shots after the Field load looked alike either way (no visible hole at that spot); per-draw use of those slots is not counted. Translator from 701e7ce: `NX2navi/build/xlate-701e7ce` (id 7b7bde78), candidate run `runs/xl701.sh` (UNCERTAIN.md). LimitReached map refusals are benign evict-and-retry.
- **#160 VRAM growth / #173 streaming.** Section 6, texture cache.
- **#172 seam.** Follow-another-descriptor (`TEX_DESC_STRICT`).
- **#168 grass.** Grass uses direct mesh draws; indirect mesh records are zero and the readback is right; cause open.
- **Hedge leaves / GPU foliage (f6702, Hyrule Castle courtyard).** Every indirect mesh draw of the frame (45: depth prepass 0129-0139, shadows 0157-0177, G-buffer 0202-0212; no task shader, ms e.g. 064a675a, fs 55ff9d82 sampling a 128x128x200-layer array atlas, tex 708) has record count 0. Their arg buffers (0x2a01e4000, 0x29fd80000, 0x29d7b6000, 0x2a0ccc010 ...) are bound as SSBOs only by passes 0001-0013, which are `DispatchComputeIndirect` (dumps print indirect dispatches as `0x0x0`, `op_dispatch_ind` in `runtime/vk_exec_draw.c`). So the foliage chain is GPU-driven from frame start; whether its own indirect group counts are 0 (nothing generated upstream) or its output is wrong is not visible: dumps do not read back indirect dispatch args. Near courtyard hedges render as bare vine cores (shot-06696) while far ones keep baked leaves; unproven that the leaves are these draws.

Patches since 0051 (README has each entry): 0052/0065 RT dedicated + trim, 0053-0063 watch/buf/dump/pick tooling, 0064 I2F sign, 0066/0068 gone rule, 0067 mesh draws in dumps, 0069 cfg row, 0070 unresolved reasons, 0071 find/poke.req, 0072 live evict, 0073 upstream 42ae87b port, 0074 STALE_LIVE, 0075/0078 RT recycle, 0076 live RT idle, 0077 VMA block size, 0079 DESC_STRICT.

- **#138 bushes.** Not a renderer problem: the leaf cards are never drawn. The cause is in the lifted game's LOD/cull decision.
- **#128 intro audio.** Game timing: atk's per-frame update starts voices per present, and `ostep` does not cover that path.

**Upstream rebase 2026-11-12, 0.9.2** (0110: branch `rebase4` in `.lab/wt-rebase4`, play44's 65 commits onto
origin/main a32597b, 124 upstream commits past 322d7c0; exe `play46`). All 65 kept; conflicts were context only
(DUMP_KEY beside DUMP_REQ, joystick mapping beside the Steam pad rule, cfg rows, mesh ring's new cb argument, the
free camera's `camavoid` in the test-script help). New upstream defaults that bear on our knobs: replay on the
submitting thread (`REPLAY_ASYNC=0`, 0533b30), replay workers 0 (94dd340), `MIRROR_HOT=0`, lifted code -O1
(`GUEST_OPT=1`), `SUBMIT_THREAD=1` on Linux (bfa486c: Mesa submit thread), `REG_ORDER=1` (857d22f: slot
registrations wait until the submission is queued, `vk_backend.c`), slope depth bias scaled with the shadow map
(58efccd/5e71cee), low-end GPU mode (mesh emulation, staged mirror uploads, VMA heap budgets; a464ffa) only with
`LOW_END_GPU=1`. Our `POOL_IDLE_MS` lookup and `POOL_LOAD_FIT` sit beside upstream's make-time accounting
(57a15e2 `vk_texture_pool_make_ns_take`): FIT still times the whole refresh. Translator sources unchanged: xlate-play33.

**Upstream rebase 2026-11-13, v0.9.2-12** (branch `rebase5` in `.lab/wt-rebase5`: skysh a01af7b's 70 commits (play49
+ 0114 + 0118) + 0115 + 0116 onto origin/main a01910d, 10 upstream commits past a32597b; exe `play50`). All 72 kept,
none covered upstream; 8 conflict hunks, context only (WATCH beside the early tail's `op_update_ub` branch, cfg rows
beside the new co-op keys, TRACE item `coop` gone with the 0.8 co-op so 0022/0035 drop it, exit timing beside
`coop_shutdown`, crosshair beside `coop_draws`, `debug_tools.h` include). **The perf/multicore-replay branch is
already in a32597b**: its 7 commits are on main as 85af8a8, 3010a63, 4fc32e8, 7534193, 77ae0f6, a0a7548 (query slots
in stream order) and 9fe3dd3, so play49's "REPLAY_WORKERS=3 no gain" was measured with the slot-order fix; merging
`origin/perf/multicore-replay` again gives ~100 hunks only because the same changes carry other SHAs. New upstream,
all off by default: `NX2NAVI_TAIL_EARLY` (aec5e72, vk_exec.c "the early tail", vk_sync.c `vk_sync_tail_hold/release`):
from the temporal upscaler's `evaluate` (vk_dlaa.c) the replay records the frame's tail into its own command buffer and,
when the tail hands the CPU only timestamps, writes no pool memory and reads no guest memory late, queues the
write-backs before it with the executed timeline's signal, so the game's wait ends before the upscaler+HUD run. It
needs a temporal upscaler (DLSS, FSR 4, FSR 3.1: on Linux only through 0112's `NX2NAVI_FFX_LIB`), `WB_SPLIT` (off under
shadow storage, on with #730 dma-bufs), native mesh shaders, and no dump; a tail that binds a pool with no VRAM mirror
(`vk_mem_note_live`: an import, host pointer or #730 dma-buf, vk_memory.c `vk_mem_use`) is refused, so count tails in the `perf: early tail:` line
(TRACE=perf, per 600) before reading an fps change. `NX2NAVI_REPLAY_SMALL=N` (8613145, needs `REPLAY_PIPE`): a group of
N+ draws too small to cut goes whole to one worker. 0109 GATE, 0114 HOLD (prologue of the first part, before the tail's
cut) and 0118 snapshots sit before any tail cut, so they are untouched by it. Translator sources unchanged: xlate-play33.

## 11. Working rules and tooling

- **cfg rule.** Every key read with `cfg_value`/`cfg_bool`/`cfg_int`/`cfg_double` needs a row in the settings table in `runtime/cfg.c`, or the game stops at start with `cfg: X has no row in the settings table` (play6, fixed by 0069). `cfg_get` alone does not need one.
- **Builds.** Build a variant only from a clean, committed tree (a worktree such as `.lab/wt-<name>` at a named commit): play20 was built over uncommitted edits of other agents, so its contents could not be named afterwards. Record the commit in the README entry.
- **Provenance (patch 0087, `runtime/provenance.c`).** The first log line is `[host] build: entry=<NX2NAVI_RUN_NAME> exe=<name> commit=<git short> xlate=<dir>/<id12> knobs=<every NX2NAVI_*, sorted>`; the same line is `build.txt` in every dump, flight, RenderDoc, shots and mark-ring folder, `shot-<n>.build.txt` beside each requested/mark shot, and `# build: ...` in input-*.txt headers. The commit is baked by `build-linux.py` (`-DNX2NAVI_BUILD_COMMIT`, provenance.c only; `-dirty` when tracked files differ). `just run <name>`, runs/*.sh and try-* set `NX2NAVI_RUN_NAME`. **Rule: every finding, tracker note and report about a symptom cites the build line (entry + exe + commit) it was seen on**; logs from exes before 0087 have no line: name the exe from the run script and say so.
- **Current recipes (#177, 2026-11-12).** `just run` = `runs/play.sh`: the rebased build (`nx2navi.play32`, patches through 0096; the exe name is one variable, `NX2NAVI_EXE` overrides) with the live-debug requests, rebase translator and caches, STALL_MS=100, SHADOW_BULK_WRITE, TEX_DESC_STRICT, RELEASED_MB 3072, then `just play-text` (text mod) -> `just play`. `just run play13` = fallback, the pre-rebase build with the old try-vram settings inlined. The `try*` recipes and the dead rebase knobs (AO_ORDER, TEX_RT_RECYCLE, TEX_STALE_LIVE, TEX_RELEASED_LRU, plus RT_TRIM, LIVE_IDLE, RELEASED_YIELD/MIB) are gone from the rebase entry; they live only in `runs/play13.sh`. Check the justfile, not this list, before telling Cal a command.
- **Dumps (`runtime/vk_dump.c`).** `NX2NAVI_DUMP_REQ=1`, then touch `dump.req`. It may hold `buf=<spec>|off ubo=<n> draws=0|1 skip_runs=0|1`, kept for later dumps. `draws=1` (per-draw images, `NX2NAVI_DUMP_DRAWS`) lands on a later frame than requested: read the frame number from the folder name. `passes.txt` lists passes, draws with shader hashes, bindings and c-bank addresses; `gpu_owned/written-since` does not count compute image stores. Mesh draws are in dumps since 0067 (`ts/ms/fs`); `mesh.txt` holds each indirect mesh draw's `{count, first}` record read after the fence (frame, pass, draw, address). Picks (`pick.req`, F5) list draws covering the centre pixel. `watch.req`, `buf.req`, `find.req`/`poke.req` need `NX2NAVI_WATCH_REQ=1`. `NX2NAVI_WATCH` is GPU-side; CPU counters need a `/proc/pid/mem` sampler or gdb.
- **Shader hot-reload facts (read from the code, `gfx_shader.c` ~1890, `vk_pipeline.c` ~3970).** The watch is inotify on the cache folder (`IN_CLOSE_WRITE|IN_MOVED_TO`) and only acts on names that are exactly `<64 hex>.spv`, so a temp file named otherwise is ignored; the `.res.json` interface is not re-read (variants must keep it). Log lines: `gfx_shader: reload: watching <dir>` at start (proof reload is on, and which folder), then `vk_pipeline: reload <key16> ok: N pipelines rebuilt after M frames` / `ok: not in use` / `failed: ...`. Control files (`shot.req`, `pick.req`) and `logs/` sit beside the cache folder (`<cache>/..`), so a lab run's are in `.lab/<label>/`. `tools/ab` automates the loop (README "Automatic A/B"); `lab-run` has `LAB_HOOK`.
- **Software runs.** `LAB_SOFT=1 tools/lab-run` renders on lavapipe (mesh shaders, float64, descriptor indexing all present), about 6 fps at render scale 50, no GPU opened, may overlap Cal's play. Not for perf or GPU-specific bugs: subgroup size is 8, not 32.
- **Replays.** Only standing-still windows measure; recordings drift and late frames are not repeatable. Castle 1500 and graveyard gate repeat within RMSE 0.07 (broken pictures 0.24+). `scenarios/` + `just regress`.
- **Game data.** MSBT text in 1.1.1 is UTF-8, "Link" is literal (no name tag); text mods via `tools/msgmod.py` / `itemtext.py` and `NX2NAVI_MODS_DIR` (`runtime/mods.c`). Switch 2 BNTX block-linear keeps Switch 1's GOB order but orders the 16-byte units inside a GOB x/32, y/4, x/16, y/2, y; BRTI +0x34 is log2 GOB rows (`tools/modelx.py`).
- **Upstream tools.** Reach for `NX2navi/tools/` before writing new scripts; see "Tools" below.

### Results record: results.tsv, builds.tsv, SYMPTOMS.md (2026-11-12)
- `builds.tsv` (one row per exe; `tools/builds-add`): exe, date, commit, xlate, base (upstream commit + tag), parent build, patch numbers contained (matched from `patches/*.patch` by commit subject; the rest listed as `unnumbered`), `changed` vs parent (patches +/-, base bump, translator), the runs/ script and its default knobs. Backfilled for play13..play38 and the sl/play34p variants; play13's log commit c7102bb is in no repo (contents from wt-play13), play22's commit is inferred, sl* were built dirty.
- `results.tsv` (`tools/results-add`; ab-cell, load-cell and `tools/suite` call it): date, entry, exe, commit, xlate, scenario, metric, mean, min, max, n, tool, source, knobs (only knobs that differ from the exe's defaults in builds.tsv). Rows are deduplicated on (entry, scenario, metric, source). n=1 is indicative. Pre-fix `ab_interval` rows (dump-window artifact) are left out. Backfill: ab-*, lc-* and the .lab/pr-* last 60 s windows (play13/31/32 parity runs); single parity windows are n=1.
- `SYMPTOMS.md`: one table row per reported symptom with first-seen build, status (open/fixed/mitigated/regressed), build where it changed, evidence. Add a row for every new symptom and update `changed in` when a build moves it.
- Suite (`tools/suite`, `just suite <exe>`): fixed cells at 3 reps: west and graveyard standing (fps, 1% low, >25 ms), cold load west/grave, scripted running (`tools/suite-run`, noted noisy while spread > 15%), replay + shadow-sync ms/frame at west, VRAM + live textures after a 4-round teleport loop, fixed-position shots paired with the parent's (tools/visual-pair, below). About 25 min GPU per build, so it is not an iteration tool. `tools/nightly` picks builds (baselines play13 + the default of runs/play.sh, newest per line, significant changes, bisect midpoints), runs the suite under the lab lock, bisects metric moves along the parent chains, writes `.lab/nightly/<date>.md`. Cal schedules it; it stops when a play log is under 2 min old.
- Phase 2 (2026-11-12): `build/store/<exe>-<commit>/` (`tools/store-build store|verify|restore`, NX2navi/build/store, reflink copies of the exe + translator dir, SHA256, `store` column of builds.tsv; hashes taken post hoc for play13..play38, so an exe overwritten earlier is stored as it was found; play21 and sl* have no exe). ab-cell/load-cell refuse an exe that differs from its stored hash; suite and nightly also refuse an unstored one. Build lock: every build under `flock /tmp/nx2navi-build.lock`; nightly holds it for its whole run (builds wait), records load average and GPU clock state per build, and counts `status` != ok rows (results.tsv column: crash, devloss, nostart, from `results-add status`) as regressions. Retention (Cal): nightly prunes store dirs and v111 exes of builds a nightly has recorded, except baselines, the default, pending bisect candidates/endpoints and the newest on an active line, and reports GB freed. Nightly writes the digest line `~/claude/.services/digest/inputs/nx2navi.txt`. Phase 2b (2026-11-12) below closes 2, 3, 5, 6, 8.
- Phase 2b (2026-11-12). results.tsv columns `env cache recipe` (header migrated; older rows empty). `env` = `tools/host-env` hash (Mesa from the run log's `vk caps` line, kernel, vbios, GPU perf level + sclk/mclk levels, power cap, CPU governor, RADV_/MESA_/ACO_/AMD_ env), full list in `.lab/env/<hash>.txt`; nightly reports an env change as `Host env DRIFT`, never compares (bisect) rows of different env, and marks a regression across envs as drift. `cache` = warm|cold|mixed from `<run dir>/cell.txt` (`tools/cell-lib.sh`: shader dir non-empty and pipeline file non-empty at the run's start). `recipe` = hash of `tools/scenarios/<name>.dbg` (Cal: scenarios are crafted, not save snapshots): `# base:` one fixed neutral base profile `.lab/scenarios/base-profile` (made once by `tools/recipe init-base`, reading the live profile; lab-run copies it per run via `LAB_PROFILE_SRC`), `# warp:` the warp-save args, then upstream `NX2NAVI_DBG_TEST` lines (`runtime/debug_tools.c` test_script ~l.993: flag, find/next/setfirst/holdfirst, freecam/camgo, warp, event, speed). Cells use recipes only with `SCENARIO_RECIPES=1` (suite sets it). Time of day is NOT pinned by name yet: progress.sav key names guessed via mm3 (*Time*, *DayTime*, Sequence_/World_/Env_ prefixes) all miss; a v1 recipe (below, "Recipes") carries every scalar game data value, so the clock comes along if it is game data (unverified). Items: no give command upstream; not needed by the perf scenarios. `results-add cal <play-*.log>`: Cal's sessions as scenario `cal-play`, tool `cal`, fps / 1% low / >25 ms per min over all full 60 s windows (n = windows), knobs note naming SYMPTOMS.md rows that cite the exe; nightly ingests finished logs. Nightly also fetches upstream and flags commits since `.lab/nightly/upstream-seen` (first night: merge-base of rebase-upstream) that touch a file any `patches/*.patch` touches (cfg.c and docs/ not counted: every knob touches cfg.c).
- Load gate (2026-11-12): ab-cell, load-cell and suite-run all wait for a 1-min load average under `LOAD_MAX` (6) before each run and write load before/after to cell.txt; with `CELL_REDO=1` (nightly) a run whose load after is above LOAD_MAX+2 is redone once.
- Suite windows (2026-11-12): the standing runs (FRAME=4200, 70 s) never had the two full `frametime: 60 s` windows results-add needed, so the first suites wrote no fps rows; results-add now falls back to the `present:` intervals from frame 2400 to the end minus 120 frames (shot/dump). Mean fps includes the hitches, 1% low is the 99th percentile interval, so mean can sit below 1% low when a few multi-second stalls fall in the window.
- Suite time (2026-11-12): the cold-load cells were dropped: the standing runs are the same warp + save load, and load-stat reads `ab-*-<west|grave>-<n>` as a cold run, so cold load rows come from those logs. 16 boots -> 10; measured play32 21.7 min (1304 s) at 3 reps, was ~40.
- Nightly selection (ranked, 2026-11-12, `pick()` in tools/nightly): tier 1 play13 + the default of runs/play.sh; tier 2 the newest candidate of each active line = an exe a `runs/*.sh` names, built in the last 3 days, untested, with no candidate descendant unless a base/translator bump lies between (play38 and play41 both run); queued cells (`.lab/nightly/cells.txt`, e.g. `tools/visual-cell <exe> <recipe> <A knob> <B knob>`) run after tier 2; tier 3 untested significant changes newest first; tier 4 bisect midpoints. Default-off experiments and lab variants never get a suite. A build whose builds.tsv parent is not an exe (play39: '74266d8') is never 'significant'. Cells take the translator from builds.tsv (`cell_xlate`: play41 -> xlate-play33) unless XLATE is set; before, every rebase-line run used xlate-rebase. Pruning also keeps exes named by runs/*.sh and by queued cells.
- Pruning (reviewed 2026-11-12, `tests/nightly-prune.py`, fake tree, 20 checks): fixed in tools/nightly: builds inside an unresolved bisect range were pruned when tested (only the queued midpoint was kept); endpoints were kept only while a midpoint sat in the queue; Cal's exe was not protected (now: the exe in the newest play log's build line at any age, plus any visible process from build/v111; and nothing at all while a play log is under 2 min old); store paths were not checked (now: must resolve to build/store/<exe>-<commit>, exe name `play*`, regular file in build/v111); the pruned row overwrote the last column instead of `store`. `NIGHTLY_DRY=1 tools/nightly` prints tonight's picks (marking those beyond the budget), what would be pruned once they are tested, what stays and why, env drift and upstream flags.
- Visual pairs (2026-11-12, Cal): `tools/visual-pair A.png B.png <scenario> <A label> <B label> [ab|parent]` stores full-res + thumbs in `.lab/visual/<date>/<exe>-<scenario>-<A|B|parent|child>.png` (outside the build store: never pruned), a diff heatmap, and a `visual.tsv` row (id, date, scenario, recipe, kind, a, b, paths, score, status, note). Score (`tools/visual-score`): linear-light |A-B| over RGB, 32x32 tile means, tiles under `tools/scenarios/<name>.mask` rectangles dropped, 95th percentile tile. Status auto-same / flagged by the scenario's `threshold` line, then cal-good / cal-bad from `/results/review.html` (slider, flip, side by side, heatmap; POST `review` in `tools/results-serve`); cal-bad appends a SYMPTOMS.md row. Calibration on same-build repeat finals (`.lab/ab-*-<sc>-1` vs `-2`): field-west 6 pairs 0.0076-0.0108 -> threshold 0.016; graveyard 8 pairs 0.0171-0.0247 (flames, fog) -> 0.037; no masks yet. The suite pairs each standing shot with the parent build's; ab-cell has no per-side shot (A and B alternate within one run), so ab-cell/load-cell make no pairs yet. Nightly lists the top 3 flagged pairs of the night as `Needs Cal`.
- Page: service `~/claude/.services/results/` (relative links, symlinks to the three files): charts per scenario/metric across builds with the build's change vs parent in the tooltip, and done-vs-open symptoms.

### Tools: problem -> tool (2026-11-11)

All upstream analysers are portable: `runtime/perf.c`, `runtime/flight.c` and `kernel.c` crit recording build on Linux (`build-linux.py` globs `runtime/*.c`, only `prof_win.c`'s sampler is Windows-only). They need their knob at run time; none of our runs set them yet. Python ones that import numpy/PIL run only inside the dev shell (`.venv`'s numpy needs the shell's libstdc++): use the just recipes.

| Problem | Tool | Input / knob |
|---|---|---|
| A/B of two runs per build (fps, 1% low, >25/50/100 ms per minute, >25 ms causes, shadow sync per 600 frames, stall sites) | `just logstat A [B]` (`tools/logstat`, ours) | stock log lines: `build:`, `frametime: 60 s`, `mem: shadow at frame`, `stall:` |
| Replay drift in A/B (#132/#173) | `NX2NAVI_AB=<s>` + a knob set to `ab`, then `just ab LOG` (`ab_summary.py`) | `runtime/perf.c` `rt_ab`/`rt_knob`, `host.h` `RT_KNOB_ON`: ABBA blocks of game time in ONE run, so the scene is the same for A and B. Needs `NX2NAVI_TRACE=perf`. Only knobs tested with `RT_KNOB_ON(mode)` per use switch live; ours (`SHADOW_NT`, `SHADOW_WB_REARM`, `vk_memory.c`) test `rt_knob(..) == 1` once, so `ab` reads as off: make new knobs `RT_KNOB_ON`. |
| Per-60-frame render-thread blocking, gpu idle, sched states | `NX2NAVI_TRACE=perf,sched`, `just perf-summary LOG a b` | `perf: frame` lines (`perf.c` perf_present), `sched:` (`kernel.c`) |
| Which thread/wait sets each frame's length (stalls, main waiting on replay) | `NX2NAVI_CRIT=a-b NX2NAVI_TRACE=sched`, `just crit crit.bin` (`crit_path.py`) | `kernel.c` crit_frame; walks wakes back from each present |
| Spikes with pictures | `NX2NAVI_FLIGHT=1` (ring 600, dump on >100 ms, F8, `_AT`, `_EVERY`), `just flight build/flight/<dump>` | `flight.c`; contact sheet + outlier counts |
| Shader translation offline | `shader_census.py --translate`, `xlate_smoke.py`, `check_isa.py`, `shader_list.py` | extracted RomFS; no GPU |
| What a thread does during given presents (a long replay frame), on and off the CPU; perf(1) is not allowed in the container | `NX2NAVI_PROFILE=<file> NX2NAVI_PROFILE_FRAMES=a-b`, then `tools/prof-window <file> <exe or nm -n output> --frames a-b --tree 12` (ours) | `runtime-linux/prof_linux.c` behind `perf.c`'s weak `prof_sampler_*`: 1 kHz signal + backtrace, each sample weighted by the time since the thread's last one |
| Area loads: freeze length and lost time per load, repeated in one session | `tools/load-cell <exe> <tag> <reps>` (live `NX2NAVI_DBG_TEST` warps; `COLD=west\|grave` one boot), `tools/load-stat --table .lab/lc-*/run.log` (ours) | `present:` lines (`NX2NAVI_TRACE=present`), `previous picture stayed` |
| Spin-wait loops holding virtual cores | `spin_waits.py` | ExeFS; emits patch-table lines |
| Guest PGO | `pgo.py` (llvm-mingw, Windows build path) | not usable on our Linux link as is |

### Upstream 0.10.1 lab tools we use (2026-11-14, all in `build` d2d2e64 = play51/deck5 and up101 5ae55db)

- **Capture-start runs** (upstream 4fd70e3, `runtime/bugcap.c`, `docs/bug-capture.md`): `NX2NAVI_CAPTURE_AT=<frame>`
  (or F8) writes `logs/captures/NNN-<time>/` (`capture.txt` place/camera/timing, `frame.png`, `frames.tsv`,
  `settings.ini`, the save as `NX2navi-save-*.zip`); `NX2NAVI_CAPTURE_DIR` moves it. A run with
  `NX2NAVI_CAPTURE_REPLAY=<dir>` presses A itself until Link appears, teleports to the nearest start, walks Link to the
  captured x z (0.4-0.5 m, he is walked, not put), places the free camera exactly and logs
  `capture: replay of <name> ready: ... m from the captured place`, then takes its own capture. No boot-timed input
  script: it does not break when boot timing shifts (scn-stand.txt does). The capture's `settings.ini` REPLACES
  nx2navi.ini (not read, not written; env still wins), so `tools/cap-prep` puts the reference ini (Cal's live one,
  copied) in as settings.ini: both A/B sides then run Cal's whole ini and no game folder's ini is touched. The save
  goes in as `profile/save-import` (fs_host.c import_pending). Ours: `tools/cap-prep`, `tools/cap-cell <exe|up101>
  <capture> <tag> <reps>` (desktop, window = `ready` + SKIPF 300 frames to FRAME, `tools/cap-sum`),
  `tools/deck/capcell.sh <up|d5> <capture> <tag>` (Deck; copy cap-prep + cap-sum to ~/nx2navi). Captures: `.lab/caps/`.
  Not restored by a replay: time of day, actors, Link's pose/item, progress since the last save. Our recipes (0106,
  exact position via warp-save) stay the tool for exact-place bugs; captures are the tool for boot-robust standing
  cells and for upstream builds, which have no recipe patch. Checked 2026-11-14: one field-mid-standing capture
  (made on play51 d2d2e64 by scn-cell + NX2NAVI_CAPTURE_AT=2700) replays on play51 and on up101 5ae55db alike: ready at
  present 2259 / 2369, Link 0.05 m off, no teleport, Cal's ini read (30 keys). Pitfall: never stage the capture inside
  `.lab/<label>`: lab-run empties its out dir, and the run then has no settings.ini (all defaults) and no replay.
  The f2663 capture (.lab/caps/f2663/001-*) walks 0.32-0.35 m (save starts 3 m away) on both builds as well.
- **Stutter map** (97671e8, e7c2fc6; `runtime/stutter_map.c`): `NX2NAVI_STUTTER_MAP=1` / ini `stutter_map = 1`, off by
  default; a hitch = a frame long against the median of the last 32 (a steady pace change is not a hitch); every 10 min
  and at exit `stutter map` blocks rank areas by hitches with causes and the pipelines/shaders draws met missing.
  `python3 NX2navi/tools/stutter_map.py report LOG` makes the report; `missing GAME_DIR LIST` lists pipelines a list lacks.
  Lab check (play51 d2d2e64, scn-cell field-running x1, 6400 frames, indicative): our `over25_min` said 341.7 a
  minute where the map counted 24 hitches in play and 1008 long frames as a change of pace: >25 ms counts a slow
  steady pace as stutter; use the map's hitches for stutter questions (#173). The run's route drifted into Market_Adult
  for 3.2 min (the field-west warp is beside the Market entrance), so area rows show where a replay really went.
- **Memory report** (d9429b0, 2820781; `vk_memory.c` owner_log/beyond_log, `mem_growth.h`): `mem: by owner`, `mem: host`,
  `mem: outside VMA`, `mem: system`, `mem: growth` (>64 MiB) and `mem: growth ranking` (10 min + exit). Covers what our
  patch 0037 (per-heap VRAM line every 1800 frames without TRACE=perf) gave. `mem_budget_test_vram_mb` / `_ram_mb` (0c153c1) pretend a small card or RAM on
  the desktop: the way to reproduce Deck memory pressure without the Deck (texture cache rules are left alone).
- **floor_watch** (cae09a2): hardware watchpoints are Windows-only (`platform/win32.c`); on Linux only floor_scan works.

- **Deck capture cells** (2026-11-14, `tools/deck/capcell.sh`, reached through `tools/deck/dssh` = 10.77.0.4 via the
  relay; steamdeckoled.local does not resolve in the container): field-mid capture deck5 d2d2e64 18.3-18.7 fps, gpu 24 ms,
  replay 19 ms (x3); the f2663 capture stops at the cell's LOWMEM 300 MiB guard right after `ready` on deck5 and slim2
  alike (MemAvailable 280-299 MiB): f2663 does not fit the Deck at Cal's Deck ini, field-mid does (min 329-590 MiB).
- **build = slim** (2026-11-14, 701e7ce, patch 0123): 9 dead or upstream-covered patches reverted, -664 lines; old tip
  `archive/pre-slim`.

### Launcher and what a run uses (2026-11-12)
`just launcher` (`launcher/`, README "Launcher") reads which exe and caches the default run uses without starting it:
the `runs/*.sh` chain ends in `exec just -f <justfile> play`, so running the script with a stand-in `just` first on
PATH that does `env -0` yields its final environment (`launcher/src/run.rs` Plan::probe; play49: exe play49,
`shader-cache-rebase`, `pipeline-cache-rebase.bin`, `xlate-play33`). Game files are found the runtime's way
(`runtime/main.c` portable_paths: NX2NAVI_EXEFS/NX2NAVI_ROMFS, else `exefs/`+`romfs/` beside the exe, else the baked
`build/extracted/v111`); 1.1.1 = main.npdm ACI0 program id 0x0400486024DEC000 (ACI0 offset at 0x70, id at +0x10)
and main's NSO build id e0f3ccfa... at 0x40 (`tools/make_game.py` check). Upstream's own launcher is Windows-only.

### A/B cells in one run: `tools/ab-cell` (2026-11-12)
`tools/ab-cell <exe> <west|grave|mid> <tag> <reps> NX2NAVI_<KNOB> [KEY=VAL...]`: lab-run `--warp` straight into the scene (save load only, no walking), the knob set to `ab` with `NX2NAVI_AB=5` (ABBA 5 s blocks, perf.c `rt_ab`), `ab_summary.py --skip 40` per run, then mean and spread of B-A over the reps (`.lab/ab-<tag>-<scene>.txt`). Warm parity caches (`.lab/parity/scR`, `pcR.bin`); FRAME=5400 is ~3 min per run. Always run a null cell beside it (`NX2NAVI_NULL_KNOB`). The perf window holding the dump frame (~280 ms a frame) must be left out: it lands on one side and read as a -13 ms B-A interval with a null knob; ab-cell drops perf windows from FRAME on (`run-ab.log`). With that, play35 (70965ce) null cells give interval B-A -0.04..-0.09 ms in Hyrule west and 0.00 in Graveyard, which runs at the 60 fps cap (16.67 ms), so Graveyard can only show replay time. Only knobs read through `RT_KNOB_ON(mode)` at each use switch live. An exe that aborts at boot (svc 0x26 Break after appletOE) was built while another build ran in `build/v111-rebase`: build under `flock /tmp/nx2navi-build.lock`.

Upstream doc facts that bear on shadow sync (`docs/building.md` "Memory"): Linux uses shadow copies because re-protecting imported memory invalidates amdgpu's userptr BO on every submit (~1.3 ms per 16 MiB) and importing pins pages, which drops userfaultfd write protection; upstream measured ~1 ms/frame of copies in Kokiri (RTX 4090). The write watch is userfaultfd async WP + `PAGEMAP_SCAN` (`PAGE_IS_WRITTEN`, re-armed with `PM_SCAN_WP_MATCHING`, kernel >= 6.7; https://docs.kernel.org/admin-guide/mm/pagemap.html), cheaper than soft-dirty. A table-binding submission copies the written pages of every CPU-visible pool once (`vk_exec_draw.c` ssbo_info -> `vk_mem_shadow_sync`), which upstream's 1 ms figure excludes: that is our table-sync cost. `NX2NAVI_SHADOW_CHECK=1` logs copy-in overwrite counts and costs every 60 frames.

### Recipes: bug reports and lab scenarios as game state (2026-11-12, patch 0106)

Bug reports and lab scenarios are **recipes**, never save states or Cal's saves (save states are infeasible:
DESIGN-savestate.md). A recipe is a text file whose first line is the format version (`# recipe v1`; a file without
one is v0, the hand-written `tools/scenarios/*.dbg` of 2026-11-12), so old marks stay readable when the format grows.
- **dump.req** dumps get `recipe.dbg` in the dump folder (vk_dump.c, same knob; patch 0107).
- **Written by the runtime** at every mark (F9, L3+R3, `mark.req`, the test script's `<tick>:mark`) and every `shot.req`:
  `logs/mark-<present>.dbg` / `logs/shot-<present>.dbg` beside the shot (`NX2NAVI_MARK_DIR` elsewhere; knob
  `NX2NAVI_MARK_RECIPE`, default 1, 0 off, 2 also `.probe` = raw game data sections + player actor for layout work).
  Code: `runtime/boot.c` moment_recipe, `runtime/debug_tools.c` dbg_mark_recipe / gd_write. Named by present, not by
  mark number, so sessions never overwrite each other's.
- **v1 content**: `# build:` line; `# mark:`; `# base:` the neutral base profile; `# warp: scene=<Sequence_CurrentBanc>
  pos=x,y,z yaw=<deg> age=adult|child` (Link's exact place: actor +0x31c position, restored exactly by the save;
  the game ignores the save's yaw keys on load (Player_Rot_For_Map, 0xa4aee8cd: saves at yaw 0, 90 and 150 spawned
  Link the same way). **Facing** shows in the actor's rotation matrix, 3x3 floats at **+0x328** (copy at +0x60c), rows
  {cos,0,-sin},{0,1,0},{sin,0,cos}, face = atan2(m[6], m[8]) (routing Link about: 85 -> -40.5 -> -51.1 deg), but writing
  it does not turn him (rewritten next frame). The spawn takes the facing from game data **float 0x1ea93bd8 = -face in
  radians** (0xa4aee8cd follows as 180 - face but alone turns nobody): a recipe restores it through its `# gd` lines
  and `tools/warp-save face=<deg>` (patch 0107 writes `face=` in the `# warp:` line). `field-gerudo-cliffs` uses face=117.82 (faces the valley, shot `.lab/mk-gerudo2`, play43). `yaw=` keeps its old, inert
  meaning so the suite scenarios keep their view. Heap scan (NX2NAVI_MARK_RECIPE=2 `facing` lines): 7 quaternions and
  dozens of matrices hold the same turn; none is reached by a pointer from the actor. The actor's +0x3c8 (1.578
  always) is not the facing); `# near:` the nearest named start position (for the live `warp`); free camera as
  `1:freecam 1 0 <speed>` + `2:camset x y z yaw pitch` (new absolute command) when it was on, else "game's own";
  `<tick>:speed` when not 1; `# gd <kind> <hash> <value>` for every scalar and `# gda <kind> <hash> <count> i:v...` for
  every 4-byte array of the game data (flags, counters, items, health, magic, rupees, but **not the time of day**: the only steadily
  running game data are uint 0xe53eb6d1 (+~1.5/s, honoured from the save) and 0xe573f564 (+~1.5/s, play time?);
  setting 0xe53eb6d1 to 0 or 720 left Hyrule Field equally at night (grey mean 0.534 both). A float search
  (test commands `findf <lo> <hi>` + `next 3` + `list <n>`, exe mark, 2026-11-12) found a heap float at **0x1373cde5c**
  (same address in two boots) rising 4.64 -> 4.81 -> 4.99 over 1800 ticks, like hours at ~0.035/s; holding it at 12
  for 600 ticks left the Market-front view at night (grey 0.536), so it is not the lighting's clock either, and the
  same base save is daylight at the Gerudo Valley gate: the visible time may be per area or scripted there. Open.); `# not captured:` actors, RNG, Link's motion/action, sound, bool arrays,
  vectors, texts (v2, patch 0116, adds vectors, 64-char texts and the game's camera: "State sync" below).
- **Game data layout** (1.1.1, manager **[main+0x4c7e180], section kind*0x60: +0x10 count, +0x18 entries, +0x20
  {hash,index} table, +0x2c its size). The kinds ARE the save's sections (progress.sav: pairs {hash,u32} from 0x28 up to
  the offset at +8, kind 0 first, each later kind opened by {0, kind}; inline values for bool/int/float/enum/uint, else
  an offset to the data; arrays = u32 count then elements). Entries start with the kind's vtable: bool 0 stride 0x18
  value byte +0x16; int 2 / float 4 / uint 20 stride 0x28 value +0x1c (+0x20 equal at a load); enum 6 stride 0x38 value
  (name hash) +0x1c; arrays int 3 / float 5 / uint 21 stride 0x40, enum 7 stride 0x50: count +0x20, elements at ptr
  +0x28 (copy at +0x38); bool array 1 stride 0x40 packed bits (not used); vec3 10 stride 0x40 floats +0x24; text64 16
  0x108. Base save: 10212 of the game's 11292 bools are in progress.sav (the rest load as defaults: a mark's value for
  those cannot be restored by save edit; warp-save prints the count).
- **Replayed by** `tools/repro <recipe> [label]`: base profile copy, `tools/warp-save scene/pos/yaw/age gd=<recipe>`
  (game data into the save, then the place), `.lab/parity/load-west.txt` loads it, the tick lines run, a second mark
  at tick 120 writes `.lab/<label>/mark/` (recipe + shot.png), `tools/repro-diff` compares (area, age, position <= 1 m,
  <= 20 game data differences). Cells: a v1 recipe kept in `tools/scenarios/` gets its game data too
  (`cell_scenario`).
- **Kept in step with development**: `tools/repro-cell <exe>` (suite step 8, so nightly) runs seed -> mark A -> repro A
  -> mark B and records `repro_ok`, `repro_pos_m`, `repro_gd_diff`, `repro_shot_score` (scenario repro-roundtrip) in
  results.tsv: a rebase or build that breaks capture (moved structures after an upstream change, a lost hook) shows
  there. **Rule**: when a bug needs state a recipe does not carry (weather, scene layer, actor spawns, an event in
  progress), add it to the format (bump to v2, keep v1 readable in repro, warp-save and repro-diff) instead of working
  around it in one investigation.

- **Reference footage (`tools/ref`).** Per-area Switch 2 footage frames in `~/claude/nx2navi/refs/` (private, never in git); git holds only tool, `tools/ref-areas.json` (area keys = names shared with teleport; scene ids are decomp numbers from memory, unverified: no scene table in `romfs_index.py` or here) and `tools/ref-index.json` (URL + t). `ref compare <shot> [area]` ranks frames by HSV histogram + colour layout + ORB inliers (HUD masked) and writes side-by-sides to the gallery. Scores are rough: different time of day, camera or HDR tonemap lowers ORB matches, so the picture, not the number, decides. YouTube "Switch 2" titles are often fan/Remake-labelled; check with `ref sheet <area>` that a segment really is the area.
- **Upstream tools.** Reach for `NX2navi/tools/` (perf_summary, crit_path, shader_census, ...) before writing new scripts.

### One codebase, one branch (Cal, 2026-11-14)

The desktop and the Steam Deck build from **one commit of the one working branch, `build`** (worktree `NX2navi/`).
Only build flags and target may differ (today both are `build-linux.py --cpu v3`, the same flags); behaviour that
differs per machine goes into runtime config (`cfg.c` device profiles such as the `DECK` table, `nx2navi.ini`), never
into a separate patch or branch. Both builds get a builds.tsv row with the same commit. Every other local line is kept
as a tag `archive/<name>` (2026-11-14: all 31 branches tagged; `play50-tip` = 15d14ce, `build-pre-deck5` = the old
`build` tip feb8e60); builds name tags or commits, never branches. On 2026-11-14 `build` was reset onto d2d2e64
(deck4, our stack + 0120 merged onto upstream v0.10.1 5ae55db): an audit of every commit in a01910d..e90b9a0 against
d2d2e64 (added lines present in the file, then each missing line checked) found nothing of play50 lacking from it;
the misses were the merge's known renames (`dbg_camera_watch_pub`, `MADE_AGE_N`, `gfx_shader_set_spirv`'s return),
reflowed `cfg.c` lists, and upstream's removal of the 0.8 co-op (`coop_local.c`).
**Fixed build dirs**: one `--out` per target, `NX2navi/build/desktop` and `NX2navi/build/deck` (seeded 2026-11-14 as
copies of `build/v111-rebase6`, deck4's and play51's out dir), so ninja objects and the lift cache are reused; never a
fresh out dir per build. (build-linux.py keeps the lift under `<extracted>/build-cache/lift`, objects under `<out>/obj`;
make_game.py keeps `<out>/build-cache`.)
First desktop smoke of play51 (d2d2e64, 2026-11-14, `.lab/d5smoke.sh`, ONE run each, machine under other agents'
builds, load 3.6-8.5: indicative): boots, no FATAL; f2663 window 1800-3000 play50 42.8 fps, play51 with upstream 0.10.1
defaults 37.3, play51 with `NX2NAVI_REPLAY_WORKERS=0 NX2NAVI_TAIL_EARLY=0` 41.4. Upstream's new defaults (workers auto,
early tail on) look slower under async replay here, as play50's A/B found for workers 2-4. Note: the f2663 recipe's
run loads HyruleField_Adult then KakarikoVillage_Adult_Alternative (~frame 1000-1100), so its window 1800-3000 is in
Kakariko, in every run since at least play50's A/B.

## 12. Glossary

- **NVN:** the Switch's native graphics API. The game calls it through a proc table; NX2navi implements it on Vulkan.
- **SVC:** supervisor call, the ARM64 instruction for a kernel request. Here it is a call to `rt_svc`.
- **Lift:** translating guest machine code into C ahead of time.
- **Guest:** the game's code and its view of memory and the OS. **Host:** the Linux process and the runtime around it.
- **Replay thread:** the host thread that turns a submitted NVN recording into Vulkan commands.
- **Shadow:** a host-visible Vulkan copy of a CPU-visible guest pool, synced before submit and written back after the fence.
  Cost signal: `mem: shadow at frame N` (runtime/vk_memory.c:1815). Kakariko Graveyard on rebase-upstream (play22, 2026-11-11, RADV 6900 XT, shadow on by default off NVIDIA blob) spent ~10 ms/frame there: 2372 pool syncs/frame, 9.4 MiB in and 3.2 MiB written back per frame; write-backs fault per page under the Linux write watch unless NX2NAVI_SHADOW_BULK_WRITE=1 (vk_memory.c shadow_bulk_write).
  Re-up cycle: on Linux a write-back's own stores, and the bulk clear (`plat_mem_prepare_write`, UFFDIO_WRITEPROTECT mode 0), both read as written to `PAGEMAP_SCAN`, so the next `snap_regions` stamped those pages in the CPU-side tables (`cgen`) and `shadow_sync_pool` merged the GPU's bytes back in: `WB_NO_REUP` only keeps `gpu_written`'s own stamps out of `cgen`, not the watch's bits. `NX2NAVI_SHADOW_WB_REARM` (0088, e1fbd67, rebase-upstream, default 1) peeks the watch before the stores and takes the bits with a resetting query after (`shadow_write_back`), restamping only CPU-written pages. Not applied in `table_wb_cb` (device-address-table stores). Effect unmeasured (play24).
- **Pin:** a reference-counted host copy of a texture's state that recordings point at.
- **One-shot pass:** a pass into targets never rendered before (a LUT or volume made once). Its draws wait for their pipeline instead of being skipped.
- **c0/c1:** NVN constant banks. c0 is driver data (storage and uniform tables, group counts) filled by the back end; c1 holds the program's own constants.
- **Patch page:** a page right after `main` (`0x7004ea0000`) that patched instructions read and the runtime writes each present (frame step, sizes, ratios).

### State sync: a running game as the reference for followers (2026-11-12, patch 0116)

One game (Cal's) is the **reference**; lab followers take on its moment, so A/B builds compare at exactly his place
without saves or hand-made recipes. The state travels as a **recipe v2** file (v1 plus `# moment: tick= speed=`,
`# camera: game x y z yaw pitch reach <camera actor>`, `# gdv 10 <hash> x,y,z` vectors (float bits) and `# gdt 16 <hash>
<text>` 64-char texts, %XX-escaped; v1 readers skip them; tools/repro, repro-diff, warp-save, recipe read both).
- **Reference** (`NX2NAVI_STATE_PUB`, default 0 off; `runtime/boot.c` state_poll from mark_poll, every 4th present):
  1 = `state.req` beside the shader cache folder writes `logs/state-<present>.dbg` (`NX2NAVI_STATE_DIR` elsewhere);
  N >= 60 also every N presents (each replacing the previous periodic one); `state-latest.dbg` is a symlink to the
  newest. Nothing in the game changes; the write is dbg_mark_recipe (~250 KB, ~13k lines) on the present thread. The
  game's camera: the free-camera patch site stays switched on with the free camera off (`dbg_camera_watch`,
  `fc.watch`): `dbg_freecam_host` notes PlayerCamera/EventCamera position and target (d0-d2, d3-d5) and runs the
  instruction it stands in for (fcvt s17, d0).
- **Follower** (`NX2NAVI_STATE_FOLLOW=<recipe>|req`, `runtime/debug_tools.c` follow_tick from dbg_tick, game thread):
  once Link has been there `NX2NAVI_STATE_FOLLOW_TICK` (60) ticks, and again at each `follow.req` (beside the shader
  cache; holds a path or nothing = the same path again, so pointing it at a reference's state-latest.dbg follows on):
  F_DATA game data: bools/ints/enums through the game's setters (SetBool main+0x682b20, SetInt main+0x163b70, enum
  main+0x3e0980; at most 16 setter calls a tick, as co-op), floats/uints/arrays/vectors by plain writes, only values
  that differ, Sequence_ControlInEvent / BancChangeFadePattern / IsEventBancChangePause / IsChildhood left; age by
  Sequence_IsChildhood before the teleport; then unless Link already stands in the area within `NX2NAVI_STATE_WARP_M`
  (0.5) m, dbg_warp to the area's start position nearest the recipe's place; `NX2NAVI_STATE_EXACT` (2; 1 position only,
  0 off) finds that start position's Trans/Rot (12 bytes, as the area's BYML holds them, `Place.rot`) in the heap and
  alias ranges, before and during the flight, and if at most 8 places hold them replaces them with the recipe's place
  and {0, -face rad, 0} until arrival (put back then); F_LAND: game data again, the free camera fixed at
  `# camera: game` (`NX2NAVI_STATE_CAM`, 1; 0 = the game's own), one `follow: done` log line (area, metres and degrees
  off, hits, game data changed after arrival).
- **Tool**: `tools/sync <state>|latest|now <exe> [label]` (SYNC_MODE=start: boot on the state by save edit as
  tools/repro, follower re-syncable via `tools/sync again [<state>]`; live: base save, then STATE_FOLLOW); `now` asks
  Cal's game through `state.req` (when its log says `state: publishing`) or `shot.req` (SHADER_RELOAD=1), read-only.
  Out: `.lab/<label>/state.dbg`, `mark/`, `diff.txt` (repro-diff, v2 also vectors + camera distance).
- **Covered**: area, Link's place, facing, age, every scalar/4-byte-array game data (flags, counters, items, health,
  rupees, magic), vectors, 64-char texts (start mode), the game's camera. **Missing**: time of day and weather (not in
  the game data, see Recipes), actors and their state, RNG, Link's motion/action, bool arrays, longer texts, sound;
  live mode cannot set texts (the area is the teleport's). Upstream co-op (`runtime/coop_game.c`) syncs progress flags
  between networked games only (no place, time or camera), through the same setters.
- **Checked (LAB_SOFT, exe sync, 2026-11-12/13; lavapipe, so times are not GPU times)**: reference write 6 ms at
  state.req (18 ms the first periodic one, cold pages): leave `NX2NAVI_STATE_PUB=1` on in play, periodic writes cost a
  hitch each. Start mode from v1 grotto-pan: Link 0.02 m, 0.0 deg off; 38 of 12867 game data differ when only the save
  carries them (bools the save does not hold, values the load resets), so start mode also runs the live data pass:
  from the reference's v2 state 0.00 m, 0.0 deg, 2 of 12867 differ (the running counter 0xe53eb6d1), vectors 2 of 26.
  Live mode from the base save at FrontOfMarket: 429 game data changed, teleport to HyruleField_FrontOfZoraRiver_UnderWater
  whose Trans was found 3 times and Rot 2 times in the heap, Link 0.00 m from the reference's place, 6 of 12867 differ.
  **The start position's Rot y is -face in radians** (as the spawn's 0x1ea93bd8): writing +face left Link 28.2 deg
  (2 x 14.09) off, fixed in d9e8adf. Worn equipment, the BGM and map names are `# gdt` texts (Armor_Adult_Goron,
  Weapon_Shield_Hylian): start mode sets them in the save, live mode does not. Float array 0x8f76b998 (32 entries, -1
  unused) counts down ~4/s (timers), not the clock. The mark's shot stops the game (FATAL) when `logs/` beside the
  shader cache is missing (boot.c shot writer has no mkdir); tools/sync makes it.

- **play50 A/B (2026-11-13, .lab/play50-ab.md).** `tools/lab-run` set `NX2NAVI_DUMP=<frame>` for every run, and an armed dump (`vk_dump_armed`, set at start, vk_dump.c) makes `vk_exec.c` skip replay worker groups (group_out: `|| vk_dump_armed`) and the early tail (`vk_exec_tail_begin`): every earlier lab `REPLAY_WORKERS` result ran 0 groups. `LAB_NODUMP=1` ends the run at a present instead. With groups really running (~1.3 groups of 362 draws a submission), workers 2/3/4 are slower than 0 on field f2663 standing (61-64 vs 66.6 fps) and field-running (79-80 vs 81.6). `TAIL_EARLY=1` with FSR 3.1 (0112 FFX_LIB, now seen dispatching on RADV): tails go early but "0 waits of the game ended before their tail": under `REPLAY_ASYNC=1` the game does not wait at that point, so no gain. With `REPLAY_ASYNC=0` it does act (the game waits on the executed timeline, `vk_sync_exec_wait`): FSR 3.1 f2663 53.5 -> 62.8 fps, field-running 60.1 -> 75.1 (3 runs each; standing all 600 tails early, moving ~30%, the rest hand the CPU results), still below async without FSR (66.6 / 81.6). play50 vs play49: same standing, +3 fps and fewer >25 ms frames moving (indicative). field-running makes ~0 texture uploads, so it does not reproduce streaming drops.

### Lab parity: run-scenario noise and upstream 0.9.0 (2026-11-12)
- The `load-run` replay (.lab/parity/run1.sh run) is too noisy for A/B: play32 (d9c9e0a) gave 47.5 fps / 174 frames >25 ms in one run and 42.1 fps / 624 in the next. Judge running-stutter changes on standing windows or with upstream's in-run ABBA (`NX2NAVI_AB`, `just ab`).
- Upstream 0.9.0 changed defaults that touch perf: `NX2NAVI_ANISO` game -> 16 (cfg.c), `NX2NAVI_FREEZE_IDLE` 60 -> 1800 (vk_memory.c freeze_idle), replay workers `NX2NAVI_REPLAY_WORKERS` (default 0, vk_exec.c). On our tree (play33, rebase2 b31135a) none moved the running numbers clearly; workers=4 was worse.
- Shadow cost per 600 frames is the same on play32 and play33 (copy-in ~2.3 s, write-back ~2.7 s, table ~1.7 s): table syncs snap ~3,000 2 MiB regions each (~6 GiB of table-shadow range, vk_memory.c vk_mem_shadow_sync / snap_tregs_runs), of which ~90 are dirty and ~770 shadows are visited.
- Shadow table sync, play35/play37 (shtouch): the replay's wait on `shadow_lock` in `shadow_touch` (completion thread merging write-backs) was worth ~1.7 ms/frame in Hyrule west (0100 TOUCH_LOCK). Visiting only stamped regions (0102 TAB_LIST) gains nothing: the per-region test over ~3,000 table regions is not a cost; the cost left in `vk_mem_shadow_sync` is the write-watch queries (`snap_regions`, ~0.8 ms/frame) and the copies (`shadow_copy`/`merge_page`, ~1.1 ms/frame), per prof_linux play34p west f2400-3100.

### Overnight lab 2026-11-13: lock order, `tools/scn-cell`, ssnap cost, pan cell
- **Lock deadlock (found 2026-11-13, fixed in `tools/lab-run` + `tools/nightly`).** `tools/nightly` holds `/tmp/nx2navi-build.lock` (python `quiet_host`, fd 3) for the whole night; `lab-run` took the lab lock, then waited `flock -w 3600` for the same build lock, so every cell run under nightly (and `tools/scn/night.sh` cells, which queue behind it) held the lab lock for an hour, timed out with exit 3 and left no `run.log` (night.out: `cell.txt`/`sum.txt` "No such file"). Now `lab-run` tries the build lock for `LAB_BUILD_TRY` s (30) while holding the lab lock, lets go of both and retries (20 s rest) up to `LAB_LOCK_WAIT` (3600), and prints `lab-run: lock timeout`; `nightly` exports `NX2NAVI_BUILD_LOCK_HELD=1` so its own cells skip the build lock. A nightly started before the fix keeps the old env: restart it. `tools/scn-cell` reports `no run.log (lab-run: ...)` and exits 3 instead of the missing-file errors.
- **`tools/scn-cell <exe> <scenario> <tag> <rep>`**: one standing run of a `tools/scenarios/<name>.dbg` recipe (title -> save load from `tools/scn-stand.txt`, no stick), Cal's play-run knobs, fps/1% low/>25 ms/interval/replay/GPU over present frames 1800..4200 into `.lab/scn-<tag>-<rep>/sum.txt`; `scn-cell sum <scenario> <tag>...` aggregates (RESULTS=1 appends results.tsv rows). Recipes: market-child, kakariko, forest-temple standing.
- **ssnap (0118) costs interval, not GPU or replay (ssnap a01af7b vs play49/skysh, indicative, 2026-11-13).** Field f2663 standing, reps 2-3 of 3 (rep 1 ran at load 7-8): play49 62.9/66.8 fps, hold 66.1/64.7, ssnap 61.5/61.9: about -3 to -4 fps (interval +1 ms); gpu ms drops 10.9 -> 9.9, replay unchanged. Market child standing (1 run each): 84.6 -> 79.7 fps (-4.9), replay 6.08 -> 5.78, gpu 6.95 -> 6.87, so the cost is on the game side of the frame (the submit-call copy of the storage buffers).
- **Pan cell: no upload churn (skysh/texchurn, `tools/pan-cell`, 9 runs).** The grotto pan cell reads `up/60 0 reup/60 0 made/60 0` in all arms, still and pan windows alike (fps 80-84, 1% low 61-68), so it cannot show whether `TEX_RELEASED_MB=6144` cuts camera-turn re-uploads: the churn Cal saw while walking is not reproduced by the scripted pan. No verdict on 6144; needs a walking recording or a field pan.

### Streaming cell: `tools/stream-cell` (2026-11-13)
- Cal's play-20261112-222948 (Zora, async on): the >=300-file windows are area loads (f1080-1260, 5760, 6120, 7860, 9960: 600-1500 files, 200-1100 textures, 36-44 fps); the rest of that session reads ~5 files/60. The 800-900-file grotto turns are in session 212219 only. `tools/stream-sum <run.log> [lo hi]` reads perf lines (files, uploaded, re-uploaded; `made` only on exes with 0115 counters, i.e. play50).
- `tools/stream-cell <exe> <tag> <reps>` + `tools/scenarios/stream-zora.dbg`: boots Zora's River, chains live warps (`NX2NAVI_DBG_TEST`), right stick held from frame 1500, LAB_NODUMP=1. Warps fire only until the Hyrule Field one (~f2480), the later ticks do nothing (not understood); after it the camera spins in Hyrule Field (FrontOfZoraRiver) for the rest of the run. Chain window 1200-2600 = loads (160-200 files/60, ~245 up/60, 74-77 fps: loads are FAST frames); spin window 2600-5800 = 25 files/60, 230-330 textures made/60 and 10-146 re-uploaded/60, 65-70 fps, period of 3 windows (the turn). It streams TEXTURES like Cal's turns but not files, and fps stays 65-70 (Cal 49.7): not a full reproduction.
- 3 runs each (indicative, camera moving): play49 spin 68.4-69.3 fps, re-up 66-111; play50 65.7-69.8, re-up 11-85; play50 null 67.3-67.6, re-up 70-146 (run-to-run spread of re-up is larger than any arm gap); RELEASED_MB 6144 on play50: 66.9/65.7/67.1 fps, re-up 42-144 vs 3072 (null+arm) 11-146: no effect visible.

### Cal's real play vs lab replays of the same input (2026-11-13, `.lab/rp.sh`, indicative)
- `.lab/rp.sh <exe> <tag>` replays `input-20261112-222948.txt` (its `profile-<ts>` bundle is picked automatically) with the play knobs, LAB_NODUMP, FRAME 13600; `.lab/rp-cmp.py <log>` (whole-run window means, % under 60/50), `.lab/rp-ts.py <cal log> <lab log> [step]` (side by side by world time). The replay IS the scenario: same scenes at the same world seconds, same draw load (binding checks/window 33.5k vs 32.0k), the Zora River load window matches (846 vs 843 files, 266 vs 266 textures).
- Same exe texchurn, per 60-frame window: Cal 64.3 fps (76% of windows under 60, 26% under 50), replay 10.0 ms, GPU 10.7 ms; lab 87.9 fps (2% under 60, 0 under 50), replay 5.5 ms, GPU 8.0 ms. play50 lab 92.7. Standing windows (0 files, 0 uploads, Zora Domain t=25-55 s) show the same gap (Cal 53 fps, rep 10-11, gpu 10-13; lab 80-90, rep 4-6, gpu 7-8.5): it is not streaming, it is the host. Unpinned (0-31) = pinned (87.8 vs 87.9). Eight nice-19 CPU hogs on cores 0-7 take the lab to 74.4 fps (replay 6.7, 10% under 60): CPU contention costs, but does not reach his replay 10 ms or GPU 10.7 ms.
- Lab differences left untested: lab display is headless sway 1920x1080 (no HDR10 surface: `hdr: the display offers no HDR10 format`, SDR decode at the present; Cal's swapchain is HDR10 format 64 on Niri at 240 Hz, game window lost focus at 22:32), the GPU is shared with the desktop compositor, his shader cache prewarmed 19.5k shaders (lab 3.3k). His GPU time is +2.7 ms for the same draws (replay parts 12.85 vs 9.83 ms in a standing window).

### Steam Deck OLED (2026-11-13, #123; tools/deck/, Deck log ~deck/nx2navi/SYSTEM-CHANGES.md)
All figures: entry as named, exe=nx2navi.play50 commit=15d14ce xlate=xlate-play33/e8d52df68016, Mesa 26.2.6 RADV VANGOGH
(the Nix closure's, not SteamOS's 26.1.99), SteamOS 3.9.5 kernel 7.2.7-valve2, measured on the Deck itself.
- **Deploy without Nix on the Deck.** `/nix` exists on SteamOS and belongs to deck: the 348 store paths of
  `nix-store -qR` over the nixVulkanIntel wrapper and the `ldd` paths of the exe and `nx2navi_xlate` (2.8 GB) are copied
  into `/nix/store` as they are. The exe has no rpath: `tools/deck/libs.sh` sets `LD_LIBRARY_PATH` from those paths
  **without glibc** (glibc in it breaks the host's `setsid`; the loader path in the ELF is absolute). The exe's baked
  ExeFS path is the build tree's (`extracted-rebase`): set `NX2NAVI_EXEFS` / `NX2NAVI_ROMFS`. play50 is `-march=x86-64-v3`
  (build-linux.py default), which Zen 2 runs. Under Steam, `unset LD_PRELOAD LD_LIBRARY_PATH` first (Steam's runtime).
- **Processes started over ssh die when the session closes** (logind): start runs as transient user units
  (`tools/deck/bg.sh`, `systemd-run --user`). The runtime's play run writes `<pipeline cache>-play.bin`.
- **The device profile acts** (`cfg.c` DECK, DMI product Galileo): fullscreen 1280x800, fifo, fps_limit 40, CORES 4,
  ASTC as BC; `NX2NAVI_DEVICE_PROFILE=desktop` turns it off. `output_res` / `render_scale` do nothing for 1.1.1 ("no
  output and scene patch sets"); the picture is `game_res` (widescreen.c: 1080 is the smallest, never narrower than 16:9,
  so the Deck shows 1280x720 with bars) and the scene is `NX2NAVI_SCENE_SHARE` of it (res_fixed, after 120 presents).
  With no settings the game draws 2560x1440 with a 1920x1080 scene and FSR shrinks it to 1280x720.
- **Memory is the first wall, not speed.** Everything the GPU sees is system RAM (14.8 GiB) and counts against amdgpu's
  cap: 1 GiB VRAM + GTT = `ttm.pages_limit` (8 GiB stock, Valve's `ttm.pages_min=2097152`). Past it the kernel logs
  `amdgpu: Not enough memory for command submission`, the game ends with "GPU device was lost", and once (two launches
  in a row under that pressure, 12:26) the kernel WARNed in `amdgpu_bo_gpu_offset` from Xwayland's submission and the
  Deck locked up. What the game needs after a save load: guest pools 5.0 GiB as shadow copies (udmabuf limit 64 MB:
  dma-bufs refused, `vk_memory.c` needs `size_limit_mb` >= 1024), or 5.4-7.0 GiB as dma-buf spans with
  `NX2NAVI_DMABUF_MB=8` (7.2+ GiB with the default 64: a span covers the aligned range around its pools), plus
  textures and targets 2.9 GiB at texture detail low. Shadow copies also cost the 5 GiB a second time in RAM
  (MemAvailable 485 MiB in a field load); host-pointer imports (`NX2NAVI_DMABUF=0 NX2NAVI_SHADOW=0`) fit but run 6.8 fps.
  With the limit at 12 GiB the automatic texture detail turns to full (budget 8781 MiB) and memory runs out again:
  force `NX2NAVI_TEXTURE_DETAIL=low`. Working set (entry f4, field): 11.9 GiB GPU-visible, MemAvailable 411 MiB.
- **System switches on the Deck** (`tools/deck/sys.sh`, root): udmabuf `size_limit_mb` 4096 (runtime value, kept by
  /etc/tmpfiles.d/nx2navi.conf) and `ttm.pages_limit=3145728` (12 GiB; GRUB_CMDLINE_LINUX_DEFAULT + update-grub, reboot).
  `vm.unprivileged_userfaultfd=0` is fine: the write watch opens its userfaultfd with UFFD_USER_MODE_ONLY (0 untracked).
- **Two Steam entries (2026-11-14).** "NX2navi (upstream)" (appid 2404835100) = clean upstream exe up101 (5ae55db,
  `ocarina` b540e1be234d) in `~deck/nx2navi/upstream` via `tools/deck/play-upstream.sh` (no NX2NAVI_ settings; upstream's
  example ini = defaults; profile copy). Built on the desktop with upstream's `tools/make_game.py --rebuild` in the flake
  shell (same Nix glibc interpreter as ours, so it runs through `libs.sh`). Do not pass `--romfs build/extracted/v111/romfs`:
  that folder is an earlier make_game output (romfs.bin + index.json) and gets packed again as a 2-file image; put the
  real romfs/ into the out folder and use `--rebuild`. "NX2navi" (3816935193) = play.sh + play.env (deck5).
  Upstream 0.10.1 reaches the title but **cannot load a save on the Deck**: with Cal's ini the GPU device is lost during
  the load (3580 of 3664 MiB budget, 64 MiB dma-buf spans), with its defaults (device profile picks texture detail full
  at the 12 GiB limit) MemAvailable falls under 100 MiB. Upstream has no memory clamp for the Deck. Same with Cal's 25 keys upstream knows in its own ini (it ignores game_res_min/max;
  game_res 900 still gives a 1920x1080 picture, 1440x810 scene, which our 0120 lowers): FATAL access violation in
  libvulkan_radeon after a failed buffer allocation during the load, MemAvailable 181 MiB (2026-11-14, abu2-1). `tools/deck/ab-up.sh`
  runs either entry at field-mid-standing (upstream needs `scn-stand-up.txt`: its boot is slower than scn-stand.txt).
- **One Steam entry with a build picker (2026-11-14).** "NX2navi" (3816935193, Exe play.sh) runs `tools/deck/pick.py`
  first when Steam starts it (`SteamGameId` set, no cell.env): SDL3 from SteamOS through ctypes, SDL_RenderDebugText,
  slim2 / slim2 + NX2NAVI_STUTTER_MAP=1 / deck5 fallback (NX2NAVI_PLAY_ENV=play.env.deck5) / upstream; last pick in
  pick.last; ~/nx2navi/pick.auto (row number, read once) picks a row after 2 s for tests through Steam.
  `NX2NAVI_PICK=<key> NX2NAVI_PICK_DRY=1` prints what a pick runs; `tools/deck/pick_test.py` feeds event structs.
  The Deck's own pad sends thousands of axis/sensor events a second: a redraw per event froze the menu behind vsync;
  drain all events, draw once a round. Never test with uinput pads on the Deck: Steam adopts them as controllers (it
  wrote preferences_/configset_<vid-pid> files for them and showed them in Cal's session).
  SDL3 event codes: 0x650 is GAMEPAD_AXIS_MOTION, 0x651 BUTTON_DOWN (the first picker read axis events as B and quit).
  Steam Input layouts of non-Steam games are keyed by the lowercased name (config/nx2navi/, configset "nx2navi"), not appid.
  play.env (play51 equivalent): play51's resolved chain minus TEX_RELEASED_MB=3072 (Deck default ~512 by RAM).
- **The desktop's full pipeline list must not be prewarmed in the game process**: without the pipeline library
  (`RADV_DEBUG=nogpl`) the boot builds every recorded pipeline and keeps it: 18,568 whole pipelines took 16 min and
  7.0 GiB private. Upstream's `tools/pipeline_list.py merge` folds recorded lists and `--prepare-pipelines` builds a
  `seed-pipeline-keys.bin` once into the caches (also held until the process ends).
  The merged list of every desktop folder (18 folders, 24,379 pipelines, 4,312 compute variants) is
  `NX2navi/build/lists/pipeline-list-merged.bin` (game-derived: never in a repository).
- **Game speed does not follow the frame rate** on this build: patch set `ostep` is on ("the game steps by the clock",
  `frame_rate.c`: 5-frame average of the display interval, longest step 1/15 s), so 30 fps runs at the right speed and
  only frames over 66.7 ms slow the game. The target on the Deck is therefore stable 30 (Cal, 2026-11-13).
- **GPU time is mostly not fill** (single runs, play50, field mid standing): scene 1280x720 29.2 ms a frame, scene
  768x432 22.9 ms: about 19 ms does not depend on the scene's size. `NX2NAVI_GPU_PASSES=1` (entry gp): 921 passes and
  dispatches a frame; passes at scene size 13.0 ms (one geometry pass 4.9 ms with 0.38M fragments, vs e341f905 fs
  6ee84266), compute 4.9 ms (froxel cs dbe3ccba 1.8, 67ebcf9b 0.9), gaps between passes 3.7 ms (barriers 1.1, target
  clears 1.0), picture-size passes 0.25 ms.
- **`texture_detail = auto` picks full on the Deck once the GPU limit is 12 GiB** and the game runs out of memory
  (entry d1: 13.9 fps, MemAvailable 257 MiB). The profile default (0120) is low; an ini line overrides it.
- **Cells must pin user-facing settings by environment**: the menu writes nx2navi.ini while a visible run is on
  screen, and the next run reads it. `gfx_window_monitor_size` is unknown at start under gamescope (deck1 fell back
  to 1440 -> clamped 1080); 0120 uses `window_size` then.
- **First frame rate (ONE run, indicative):** Hyrule Field mid standing, picture 1080, scene 1280x720, uncapped:
  19.4 fps, GPU 29.2 ms and replay 20.2 ms a frame (entry f4, system gtt 12 / udmabuf 4096 / epp balance_performance).
- **Building on the Deck, offline** (`tools/deck/deckbuild.sh`, 2026-11-13): the build tree is mirrored at the desktop's
  absolute paths (`/home/purplg/claude/nx2navi` on the Deck, so the kit venv, ninja state and ccache stay valid) and the
  dev shell is entered by sourcing `nix print-dev-env` output; its closure is 156 store paths beyond the runtime's.
  deck3 (a7db98a = deck2 + a comment patch sent as a 1.2 KB mbox) built inside `unshare -n` in 243 s on the Deck.
  deck3 was built there only (builds.tsv row, no stored copy on the desktop). Not verified: a game run with the network
  cut (the Steam entry did not start the game during or after the test; Steam logs `ExecuteSteamURL` and starts nothing;
  cause open; another agent's cargo build held every core at the time).
- **Settle detector pitfalls** (`tools/deck/stable.py`): the title scene and loading screens are steady too. A void
  "50 fps" (entry base-1, GPU 8.5 ms) was the title scene; the detector now needs a loading screen (GPU < 2 ms) first.
  No 3-run cell result exists yet: every arm of `tools/deck/plan.sh` is still to run.
- **Upstream 0.10.1 on the Deck: exe deck4** (d2d2e64, branch `rebase6`, `.lab/wt-rebase6`, 2026-11-13): upstream
  `5ae55db` (v0.10.1, 175 commits past a01910d) MERGED into the deck stack (deckres e90b9a0), not rebased commit by
  commit: 32 conflict hunks in 14 files, then three build fixes (0003's shader reload moved onto upstream's
  `spv_store.h`: `gfx_shader_set_spirv` now returns the old words; 0115's `AGE_N` renamed `MADE_AGE_N`; 0116's
  `dbg_camera_watch` renamed `dbg_camera_watch_pub` beside upstream's own). Built with `.lab/brb6.sh` into
  `build/v111-rebase6` with its own lift cache `build/extracted-rebase6` (upstream's `recomp/simd_c.py` and
  `patches-v111.txt` changed: every lifted file compiles again). Translator unchanged in use (xlate-play33; upstream's
  pool length went 32768 -> 40960 in `tools/xlate/Program.cs`, and the runtime still takes the old length).
  **Upstream has no new Steam Deck profile in this range**: the `DECK` table in `cfg.c` (40 fps, 4 cores, ASTC as BC)
  is the one play50 already had. What is new and matters there: `mem_budget.c` (levels from the card's budget and from
  MemAvailable / cgroup limits, `platform/linux.c plat_commit_info`), idle SPIR-V kept zstd-compressed
  (`spv_store.h`), unused pipelines given back under pressure (`PIPE_RELEASE`), overwritten render targets handed on
  (217fb32, 1dbecd4), released textures held by time (`TEX_RELEASED_HOLD`), `low_end_gpu` leaves async replay off.
  State: ONE direct run on the Deck (entry d4-1) booted, prewarmed and reached the save load (1,227 presents, no
  FATAL), stopped before the field. No frame rate, no desktop boot, no A/B yet.
- **Why the Steam entry "stopped launching" (14:29)**: Steam's `webhelper_js.txt` logs `SynchronizingControllerConfig
  syncfailed` and `showing cloud sync failed dialog 241100` for each `steam://rungameid`: after the offline test cut the
  network, every launch waits behind that dialog for "Play anyway" (or a Steam restart). `console_log.txt` only shows
  `ExecuteSteamURL`. `tools/deck/direct.sh <exe> <tag>` starts a pinned field run on gamescope's `DISPLAY=:1` without
  Steam (not on the panel) for such times.
- **Which exe the entry runs**: `~/nx2navi/play.env` (read by play.sh, kept): `NX2NAVI_EXE`, its own
  `NX2NAVI_PIPELINE_CACHE`. No file = deck2. `tools/deck/show.sh [exe] [scenario]` is one foreground start through the
  entry from a copy of a scenario save with the overlay on.
- **The Deck's offline build tree was deleted at 15:01 (not by this work) and recreated for the new base**:
  `/home/purplg/claude/nx2navi` (2.3 GB: `.lab/wt-rebase6` as a plain git snapshot, kit venv, lift cache, deck4's
  objects; no .ccache), `deckbuild.sh` points at it. Same dev shell store paths. Not test-built there.
