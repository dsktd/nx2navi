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

- **CPU to shadow:** before each submit, the written pages are copied into the shadow.
- **GPU to guest:** after the fence, GPU writes are copied back, page by page, only where the bytes changed (our patches 0001, 0008, 0025).

Written pages are found with a userfaultfd in asynchronous write-protect mode plus `PAGEMAP_SCAN`. This needs Linux 6.7, and Podman's default seccomp blocks it (`runtime/platform/linux.c:796-799`; `~/claude/nx2navi/README.md`, "Upstream bug").

Two lifetime mechanisms keep graphics objects alive just long enough:

- **Texture pins.** Recordings name immutable host copies of each texture initialisation. A copy is freed some submits after nothing reads it (`runtime/nvn_api_cmd.c:234-248`; play log: "6625 live, 6605 waiting").
- **Released textures.** See "Texture cache" below.

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
- **Streaming cost (#173).** Riding fast: `pool_fini` waits (1.6 s per 1800 frames), 49 ms pipeline-build spikes, 94k texture releases per 1800 frames.

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
- **Invalid SPIR-V.** Mesa rejects some modules and RADV then dereferences NULL in `radv_shader_spirv_to_nir`. Known case: a layer-count size query (component 2 of `OpImageQuerySizeLod`) on a texture typed 2D by default (`tools/txq-array-fix.py`, patch 0050; guard 0033). Check suspects with `spirv-val`.
- **Window origin.** The upper-left origin and a y-flipped viewport put NDC +y at row 0 as NVN does, so front-face winding maps unchanged (`vk_pipeline.c` `vk_pipeline_set_dynamic`).
- **FMZ.** The game's SM86 shaders never set FMZ; the sky-SH NaN was a shadow-sync bug (0004), not 0*inf.

## 8. Timing

- **The game's own pacing.** Shipping Ocarina steps its update by whole vsync intervals. Above 60 fps, gameplay, the interface and the frame counter at update `+0xd58` all run fast (`recomp/patches-v111.txt:21-28`).
- **The `ostep` patch set** (`NX2NAVI_OCARINA_REALTIME`, on) rewrites two instructions at `main+0x6e6cc0`. The per-frame update then reads frames-per-update from patch page `+256`, which `frame_rate.c` writes each present as the display interval in 60 Hz frames (play log 39-41).
- **The other sets** (`fps60`, `realtime`, `cloth`, `bounce`) belong to upstream's other title's tables (`patches-v121.txt` etc.).
- **The frame limit** is `fps_limit` / `NX2NAVI_FPS_LIMIT`, capped at 240 (`frame_rate.c:21-23`). Cal's ini currently says 60 (play log 379); the perf trace ran at 240.
- **Game time follows wall time.** The step is the moving average of the last 5 display intervals, at least 1/240 s and at most 1/15 s (`frame_rate.c:10-13, 55-58`).
- **Why replays drift.** Recorded input is keyed to game time, and game time is the measured wall time. A different frame rate gives different steps and stick-sample instants, so positions diverge (tracker #145).
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
- **HDR, upscaling, frame generation.** HDR10 native swapchain (`vk_hdr.c`; play log 52-53). The game's tensor-core upscaler is replaced by decode-and-scale (`vk_tonemap.c`). FSR 1 runs when the window is larger than the picture (`vk_fsr.c`). FSR 3.1 and DLSS paths exist (`vk_ffx.cpp`, `vk_dlaa.c`, `vk_dlssg.c`), but FSR 3.1 is missing on this host (play log 32-33). Frame generation is off in Cal's ini; whether it works on Linux is not established.
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
- **#146 AO flicker.** Replay ordering: the replay ignores `nvnCommandBufferWaitEvent`, so AO reads last frame's half-res depth and trails one frame behind motion (identical while nothing moves). On `build`/play13 `NX2NAVI_AO_ORDER=1` (0046) runs the occlusion again at the signal op; on rebase-upstream that knob is dead and upstream's event order plus 0090 `NX2NAVI_EVO_ASYNC` replace it (section 10); `NX2NAVI_AO=0` (0045) turns it off; 0013/0016 cut submissions and darken the picture.
- **#141 crash guard.** Driver faults in RADV `spirv_to_nir` during pipeline builds (0031/0033), plus device losses possibly tied to VRAM pressure.
- **#149/#169 missing or stretched terrain.** Texture cache stale rule on re-initialised height tiles (section 6; `TEX_STALE_LIVE` on `build` only, fixed upstream by finalize-own-slots on rebase-upstream). LimitReached map refusals are the game's own evict-and-retry signal and benign; a bigger `APP_POOL` only grows the heap, `NX2NAVI_ALIAS_EXTRA_MIB` gives alias room.
- **#160 VRAM growth / #173 streaming.** Section 6, texture cache.
- **#172 seam.** Follow-another-descriptor (`TEX_DESC_STRICT`).
- **#168 grass.** Grass uses direct mesh draws; indirect mesh records are zero and the readback is right; cause open.
- **Hedge leaves / GPU foliage (f6702, Hyrule Castle courtyard).** Every indirect mesh draw of the frame (45: depth prepass 0129-0139, shadows 0157-0177, G-buffer 0202-0212; no task shader, ms e.g. 064a675a, fs 55ff9d82 sampling a 128x128x200-layer array atlas, tex 708) has record count 0. Their arg buffers (0x2a01e4000, 0x29fd80000, 0x29d7b6000, 0x2a0ccc010 ...) are bound as SSBOs only by passes 0001-0013, which are `DispatchComputeIndirect` (dumps print indirect dispatches as `0x0x0`, `op_dispatch_ind` in `runtime/vk_exec_draw.c`). So the foliage chain is GPU-driven from frame start; whether its own indirect group counts are 0 (nothing generated upstream) or its output is wrong is not visible: dumps do not read back indirect dispatch args. Near courtyard hedges render as bare vine cores (shot-06696) while far ones keep baked leaves; unproven that the leaves are these draws.

Patches since 0051 (README has each entry): 0052/0065 RT dedicated + trim, 0053-0063 watch/buf/dump/pick tooling, 0064 I2F sign, 0066/0068 gone rule, 0067 mesh draws in dumps, 0069 cfg row, 0070 unresolved reasons, 0071 find/poke.req, 0072 live evict, 0073 upstream 42ae87b port, 0074 STALE_LIVE, 0075/0078 RT recycle, 0076 live RT idle, 0077 VMA block size, 0079 DESC_STRICT.

- **#138 bushes.** Not a renderer problem: the leaf cards are never drawn. The cause is in the lifted game's LOD/cull decision.
- **#128 intro audio.** Game timing: atk's per-frame update starts voices per present, and `ostep` does not cover that path.

## 11. Working rules and tooling

- **cfg rule.** Every key read with `cfg_value`/`cfg_bool`/`cfg_int`/`cfg_double` needs a row in the settings table in `runtime/cfg.c`, or the game stops at start with `cfg: X has no row in the settings table` (play6, fixed by 0069). `cfg_get` alone does not need one.
- **Builds.** Build a variant only from a clean, committed tree (a worktree such as `.lab/wt-<name>` at a named commit): play20 was built over uncommitted edits of other agents, so its contents could not be named afterwards. Record the commit in the README entry.
- **Provenance (patch 0087, `runtime/provenance.c`).** The first log line is `[host] build: entry=<NX2NAVI_RUN_NAME> exe=<name> commit=<git short> xlate=<dir>/<id12> knobs=<every NX2NAVI_*, sorted>`; the same line is `build.txt` in every dump, flight, RenderDoc, shots and mark-ring folder, `shot-<n>.build.txt` beside each requested/mark shot, and `# build: ...` in input-*.txt headers. The commit is baked by `build-linux.py` (`-DNX2NAVI_BUILD_COMMIT`, provenance.c only; `-dirty` when tracked files differ). `just run <name>`, runs/*.sh and try-* set `NX2NAVI_RUN_NAME`. **Rule: every finding, tracker note and report about a symptom cites the build line (entry + exe + commit) it was seen on**; logs from exes before 0087 have no line: name the exe from the run script and say so.
- **Current recipes (#177, 2026-11-12).** `just run` = `runs/play.sh`: the rebased build (`nx2navi.play32`, patches through 0096; the exe name is one variable, `NX2NAVI_EXE` overrides) with the live-debug requests, rebase translator and caches, STALL_MS=100, SHADOW_BULK_WRITE, TEX_DESC_STRICT, RELEASED_MB 3072, then `just play-text` (text mod) -> `just play`. `just run play13` = fallback, the pre-rebase build with the old try-vram settings inlined. The `try*` recipes and the dead rebase knobs (AO_ORDER, TEX_RT_RECYCLE, TEX_STALE_LIVE, TEX_RELEASED_LRU, plus RT_TRIM, LIVE_IDLE, RELEASED_YIELD/MIB) are gone from the rebase entry; they live only in `runs/play13.sh`. Check the justfile, not this list, before telling Cal a command.
- **Dumps (`runtime/vk_dump.c`).** `NX2NAVI_DUMP_REQ=1`, then touch `dump.req`. It may hold `buf=<spec>|off ubo=<n> draws=0|1 skip_runs=0|1`, kept for later dumps. `draws=1` (per-draw images, `NX2NAVI_DUMP_DRAWS`) lands on a later frame than requested: read the frame number from the folder name. `passes.txt` lists passes, draws with shader hashes, bindings and c-bank addresses; `gpu_owned/written-since` does not count compute image stores. Mesh draws are in dumps since 0067 (`ts/ms/fs`); `mesh.txt` holds each indirect mesh draw's `{count, first}` record read after the fence (frame, pass, draw, address). Picks (`pick.req`, F5) list draws covering the centre pixel. `watch.req`, `buf.req`, `find.req`/`poke.req` need `NX2NAVI_WATCH_REQ=1`. `NX2NAVI_WATCH` is GPU-side; CPU counters need a `/proc/pid/mem` sampler or gdb.
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
  vectors, texts.
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

### Lab parity: run-scenario noise and upstream 0.9.0 (2026-11-12)
- The `load-run` replay (.lab/parity/run1.sh run) is too noisy for A/B: play32 (d9c9e0a) gave 47.5 fps / 174 frames >25 ms in one run and 42.1 fps / 624 in the next. Judge running-stutter changes on standing windows or with upstream's in-run ABBA (`NX2NAVI_AB`, `just ab`).
- Upstream 0.9.0 changed defaults that touch perf: `NX2NAVI_ANISO` game -> 16 (cfg.c), `NX2NAVI_FREEZE_IDLE` 60 -> 1800 (vk_memory.c freeze_idle), replay workers `NX2NAVI_REPLAY_WORKERS` (default 0, vk_exec.c). On our tree (play33, rebase2 b31135a) none moved the running numbers clearly; workers=4 was worse.
- Shadow cost per 600 frames is the same on play32 and play33 (copy-in ~2.3 s, write-back ~2.7 s, table ~1.7 s): table syncs snap ~3,000 2 MiB regions each (~6 GiB of table-shadow range, vk_memory.c vk_mem_shadow_sync / snap_tregs_runs), of which ~90 are dirty and ~770 shadows are visited.
- Shadow table sync, play35/play37 (shtouch): the replay's wait on `shadow_lock` in `shadow_touch` (completion thread merging write-backs) was worth ~1.7 ms/frame in Hyrule west (0100 TOUCH_LOCK). Visiting only stamped regions (0102 TAB_LIST) gains nothing: the per-region test over ~3,000 table regions is not a cost; the cost left in `vk_mem_shadow_sync` is the write-watch queries (`snap_regions`, ~0.8 ms/frame) and the copies (`shadow_copy`/`merge_page`, ~1.1 ms/frame), per prof_linux play34p west f2400-3100.
