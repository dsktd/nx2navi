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
Because whole pipelines build slowly, the justfile also sets `NX2NAVI_PIPE_SKIP=strict`: full-screen draws wait for
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
with it: the shaders need those constants. What does work without a source change: `build-linux.py` compiles
`vk_exec_draw.c` at `-O0` (PER_FILE_FLAGS), which lays the function's locals out so that the 112 bytes land on a
dead structure; the recording replays past the spot. Cost: that file is the draw recorder, so some CPU per frame.

Container replays are not representative past that point: Podman's default seccomp profile denies `userfaultfd`, the
runtime logs "no asynchronous userfaultfd write protection" and copies whole pools to the GPU every frame (1.4 fps,
black picture, an ASTC decode storm). `--cap-add SYS_PTRACE` on the container would let it through (not added yet:
Cal's decision, it widens the sandbox); on the host the write watch works ("0 untracked" in the logs).

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
