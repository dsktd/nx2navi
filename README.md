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

2026-11-08: built in the Manager's container (lift 297,414 functions, 680 objects, 318 MB `build/v111/nx2navi`),
then run from the container on the RX 6900 XT through `/dev/dri` and the host's Wayland socket: intro movies, title
loop and the in-game menu for 12,600 frames without a fault. `--selftest` passes except one check that assumes the
other game's 3.3 GB pool. Open: the menu finds no system fonts in the container; Cal saw a rendering band on the
"Fullscreen" row; play with a pad is tested on the host (`just run`, yakin's pad).

## What was verified

In the container (no GPU, no game files): the shell enters with clang 23.1.3, lld, ninja, make, dotnet 10.0.403,
Python 3.12.15 and 3.14.8, uv 0.13.5, SDL3 3.4.18 and Vulkan 1.4.363; a test program links with upstream's Linux link
line (`-lvulkan -lSDL3 -lopus -lvpx -lzstd -l:libstdc++.a`) and runs; `uv` resolves both requirement files as wheels
for the Nix interpreters; `nixVulkanIntel` builds and points `VK_ICD_FILENAMES` at Mesa 26.2.6. Not verified: the real
game build and play.

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

## lab-run debug options

Both are opt-in environment variables for `tools/lab-run` (see its header):

- `LAB_VALIDATE=1`: Khronos validation layer from nixpkgs plus synchronization validation. Messages go to `.lab/<label>/validation.log`, at most 3 per message ID. Slow.
- `LAB_HANG=1`: `RADV_DEBUG=nogpl,hang`; the `radv_dumps_*` hang reports land in `.lab/<label>/hang`.
