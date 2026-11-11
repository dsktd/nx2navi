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
  - It also compiles `runtime-linux/frames.c`. This fixes two Linux platform gaps: setjmp/longjmp through lifted frames, and fiber stack alignment.
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
- **SKIP_SHADERS and live swaps on mesh draws (#174).** `NX2NAVI_SKIP_SHADERS` acts only at draw time (`runtime/vk_exec_draw.c` shader_skipped, checked after the shaders resolve and before any pipeline lookup, the same path for vertex and mesh draws); it never reaches pipeline creation. The start crash `libvulkan_radeon.so+0x19be92 writing 0x40` right after "4 background graphics pipeline workers" happened with that knob (play-20261111-170227) and also without it on 2026-11-10 (play-20261110-225615), both with plain `just play` on `pipeline-cache.bin`; the i2f recipes have not shown it. Hot-reload files of mesh-pipeline fragment shaders are named like any other: `<sha256 cache key>.spv` in the watched dir (`shader-cache-i2f` for the try recipes). Find one by `cmp` against the dump's `sh_<fnv>.spv` (fs 560e3938 = i2f `eeb937a7...`, byte-identical to plain `591303b6...`); a `.res.json` beside it has the same body minus `key`.
- **The critical path.** The replay thread. "frame bound 1800 calls, 0 waited" only says the present never waits for it; the game waits for it in the finish wait instead. Letting the game go before the GPU is through (`NX2NAVI_FINISH_DEFER`, patch 0036) gains nothing, and neither does faster guest code (16% of the main thread; the -O2 A/B agrees): what shortens the frame is a cheaper replay thread per draw.

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
  3. _Stale rule_: a CPU slot registered at or before its own entry's release is stale and resolves to nothing (prevents uploading from storage being unmapped). Ocarina finalises and re-initialises terrain height tiles (r32f 260x260) at the same storage without re-registering the pool slot, so they went to the dummy (#149/#169 holes and columns). `NX2NAVI_TEX_STALE_LIVE=1` (0074, default 0, on in `try-vram`) takes the entry back when `nvn_tex_live_at` shows an initialised texture of the slot's own key there. Lab: 3974 tiles recovered, 0 unresolved.
  4. _Gone rule_: own entry destroyed, slot registered before that. Default: a new **live** entry is made from the old storage (no Finalize ever releases it: a source of #160 growth). `NX2NAVI_TEX_STALE_GONE=1` (0066) resolves to nothing, but only when no live entry is at the address (0068; the unconditional version blanked live terrain).
  5. Else `entry_of` makes the entry from storage (bounded by the create budget during pool refresh).
     Every nothing-path is counted per path (stale, gone, create held, create failed) in the `mem: textures` line; the first 16 of each are logged. A dump's `tex N unresolved (dummy)` says why (0070).
- **VRAM knobs and what they cost.** VMA keeps part-empty 256 MiB blocks (`NX2NAVI_VMA_BLOCK_MIB`, 0077), so driver usage does not fall when allocations are freed; on RADV plain images share those blocks.
  - `TEX_RT_DEDICATED_MIB` (0052, default 4): render targets of that size and up get their own memory, so freeing them frees VRAM.
  - `TEX_RT_TRIM` (0052/0065, default 95, 85 in `try-vram`): drop released RTs above that share of the budget. The game takes many RTs straight back, so a trim is judged 32 submits later and backs off (`_COOLDOWN`, `_AGE` 240, `_PER_MIN` 6). Without the backoff it churned 14 GB/min with no gain.
  - `TEX_RT_RECYCLE` (0075/0078, code default 0; `just try-vram` sets 1): a new RT takes the image and memory of an idle released RT of the same description instead of allocating. This is the perf lever under streaming: off, released-RT churn (count sweep destroyed 34 GiB in 46k frames) costs about 30 fps in Hyrule; on, lab card use 84-94% vs 91-99%, worst frame 27 vs 98 ms. Risk: content lost when the game takes a recycled RT back (lighting flicker with camera/time of day, play11); 0078 skips taken-back and remade keys. With 0078, a full 46k-frame Hyrule replay (l12rt) ran clean: card 13758 of 14934 MiB at f45000 vs 14360 of 15330 on play11 (l11hold), released own memory 271 vs 1436 MiB.
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

## 9. Input, audio, HDR and scaling, saves

- **Input.** SDL3 gamepads; the pad pressed last is the game's pad (`input.c`). Our patch 0014 prefers Steam Input's virtual pad. Motion can come from a second pad (patch 0034). The six-axis sensor and rumble are served through the hid overrides (play log 357-364).
- **Audio.** The game's `nn::atk` runs as lifted code and talks to `audren:u` over in-process IPC. `audren.c` and `audio_mixer.c` mix on the host and output through SDL (play log 333-336). Open problem #128: intro narration voices start faster at higher frame rates.
- **HDR, upscaling, frame generation.** HDR10 native swapchain (`vk_hdr.c`; play log 52-53). The game's tensor-core upscaler is replaced by decode-and-scale (`vk_tonemap.c`). FSR 1 runs when the window is larger than the picture (`vk_fsr.c`). FSR 3.1 and DLSS paths exist (`vk_ffx.cpp`, `vk_dlaa.c`, `vk_dlssg.c`), but FSR 3.1 is missing on this host (play log 32-33). Frame generation is off in Cal's ini; whether it works on Linux is not established.
- **Saves.** A host save directory with a working copy; the game's `Commit` writes it (play log 339-342, 493). `just play` copies saves into each recording bundle.

- Menu settings (runtime/ui/option_rows.cpp apply): a row's change goes into memory at once (cfg_set, cfg_version bumps) and
  consumers that re-read cfg follow; nx2navi.ini is written by opt_save_tick 0.4 s later, or only by the Save button with
  `NX2NAVI_MENU_LIVE=1` (patch 0080). Which rows are live: cfg.c metas `LIVE`, plus `LIVE_WITH_MENU_LIVE` under that knob
  (cfg_live); the rest are read once at start and show "after restart". Shadow range is live-capable because the cascade
  patch set loads its distances from the patch page (+64) on each call; render targets, shadow map sizes, swapchain
  features, the game's language/operation mode and RomFS-served packs are fixed at boot.

## 10. Our private patches

All are in `~/claude/nx2navi/patches/`, as local commits on `build`. Status comes from `~/claude/nx2navi/README.md`.

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
- **#146 AO flicker.** Replay ordering: the replay ignores `nvnCommandBufferWaitEvent`, so AO reads last frame's half-res depth and trails one frame behind motion (identical while nothing moves). `NX2NAVI_AO_ORDER=1` (0046, `vk_exec.c` "ambient occlusion after its event") runs the occlusion again at the signal op; `NX2NAVI_AO=0` (0045) turns it off; 0013/0016 cut submissions and darken the picture.
- **#141 crash guard.** Driver faults in RADV `spirv_to_nir` during pipeline builds (0031/0033), plus device losses possibly tied to VRAM pressure.
- **#149/#169 missing or stretched terrain.** Texture cache stale rule on re-initialised height tiles (section 6, `TEX_STALE_LIVE`). LimitReached map refusals are the game's own evict-and-retry signal and benign; a bigger `APP_POOL` only grows the heap, `NX2NAVI_ALIAS_EXTRA_MIB` gives alias room.
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
- **Current recipes.** `just play` (stock defaults), `just try` (debug requests on), `try-i2f` (fixed translator, own caches), `try-vram` (on `try-i2f` with the VRAM hold set and `STALE_LIVE=1`; current daily recipe), `try-name NAME` (`try-vram` plus the text mod). Exes: `play11` is `try-vram`'s default, `play13` = play11 + DESC_STRICT. Check the justfile, not this list, before telling Cal a command.
- **Dumps (`runtime/vk_dump.c`).** `NX2NAVI_DUMP_REQ=1`, then touch `dump.req`. It may hold `buf=<spec>|off ubo=<n> draws=0|1 skip_runs=0|1`, kept for later dumps. `draws=1` (per-draw images, `NX2NAVI_DUMP_DRAWS`) lands on a later frame than requested: read the frame number from the folder name. `passes.txt` lists passes, draws with shader hashes, bindings and c-bank addresses; `gpu_owned/written-since` does not count compute image stores. Mesh draws are in dumps since 0067 (`ts/ms/fs`); `mesh.txt` holds each indirect mesh draw's `{count, first}` record read after the fence (frame, pass, draw, address). Picks (`pick.req`, F5) list draws covering the centre pixel. `watch.req`, `buf.req`, `find.req`/`poke.req` need `NX2NAVI_WATCH_REQ=1`. `NX2NAVI_WATCH` is GPU-side; CPU counters need a `/proc/pid/mem` sampler or gdb.
- **Software runs.** `LAB_SOFT=1 tools/lab-run` renders on lavapipe (mesh shaders, float64, descriptor indexing all present), about 6 fps at render scale 50, no GPU opened, may overlap Cal's play. Not for perf or GPU-specific bugs: subgroup size is 8, not 32.
- **Replays.** Only standing-still windows measure; recordings drift and late frames are not repeatable. Castle 1500 and graveyard gate repeat within RMSE 0.07 (broken pictures 0.24+). `scenarios/` + `just regress`.
- **Game data.** MSBT text in 1.1.1 is UTF-8, "Link" is literal (no name tag); text mods via `tools/msgmod.py` / `itemtext.py` and `NX2NAVI_MODS_DIR` (`runtime/mods.c`). Switch 2 BNTX block-linear keeps Switch 1's GOB order but orders the 16-byte units inside a GOB x/32, y/4, x/16, y/2, y; BRTI +0x34 is log2 GOB rows (`tools/modelx.py`).
- **Reference footage (`tools/ref`).** Per-area Switch 2 footage frames in `~/claude/nx2navi-ref/` (private, never in git); git holds only tool, `tools/ref-areas.json` (area keys = names shared with teleport; scene ids are decomp numbers from memory, unverified: no scene table in `romfs_index.py` or here) and `tools/ref-index.json` (URL + t). `ref compare <shot> [area]` ranks frames by HSV histogram + colour layout + ORB inliers (HUD masked) and writes side-by-sides to the gallery. Scores are rough: different time of day, camera or HDR tonemap lowers ORB matches, so the picture, not the number, decides. YouTube "Switch 2" titles are often fan/Remake-labelled; check with `ref sheet <area>` that a segment really is the area.
- **Upstream tools.** Reach for `NX2navi/tools/` (perf_summary, crit_path, shader_census, ...) before writing new scripts.

## 12. Glossary

- **NVN:** the Switch's native graphics API. The game calls it through a proc table; NX2navi implements it on Vulkan.
- **SVC:** supervisor call, the ARM64 instruction for a kernel request. Here it is a call to `rt_svc`.
- **Lift:** translating guest machine code into C ahead of time.
- **Guest:** the game's code and its view of memory and the OS. **Host:** the Linux process and the runtime around it.
- **Replay thread:** the host thread that turns a submitted NVN recording into Vulkan commands.
- **Shadow:** a host-visible Vulkan copy of a CPU-visible guest pool, synced before submit and written back after the fence.
- **Pin:** a reference-counted host copy of a texture's state that recordings point at.
- **One-shot pass:** a pass into targets never rendered before (a LUT or volume made once). Its draws wait for their pipeline instead of being skipped.
- **c0/c1:** NVN constant banks. c0 is driver data (storage and uniform tables, group counts) filled by the back end; c1 holds the program's own constants.
- **Patch page:** a page right after `main` (`0x7004ea0000`) that patched instructions read and the runtime writes each present (frame step, sizes, ratios).
