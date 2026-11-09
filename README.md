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

2026-11-09 (morning). The game is played daily on the host (`just play`): Cal's save is in Hyrule Castle / Hyrule
Field, HDR10 native through niri-spicy, 240 Hz panel. Since the 2026-11-08 morning build:

- Lighting fixed at the source: the shadow sync skipped the CPU's per-frame zeroing of the sky-SH block, so the GPU
  kept adding into stale (or NaN) sums (patch 0004, build f33ed65). The pow NaN stopgaps are obsolete; `fmzpow` is still
  run until a fresh-cache test proves it unneeded (NOTES "fmz-pow after f33ed65").
- Performance 52 -> 64 fps in the haze replay: changed-page write-back (0001), the page compare outside shadow_lock
  (0008), compact freshness arrays (0009), neighbouring-pool queries (0010), async replay and recorder thread on by
  default. Heavy field scenes still drop to 36-46 fps under VRAM pressure (#132): the released-texture list holds
  7-8 GiB of render targets while small textures are evicted and re-uploaded (NOTES "VRAM pressure"); patch 0019's
  byte cap is built, off by default, untested.
- Debug and play features: shader hot-reload and on-request shots (0003), dump.req (0011), mark this moment (0015,
  F9 / L3+R3), draw lists in dumps (0017), Steam Input pad preferred (0014), projection unjitter (0012).
- Defaults: `NX2NAVI_PIPE_SKIP=any`, `NX2NAVI_HDR=native`, `REPLAY_ASYNC=1`, `VK_RECORDER=1`.
- AO: the event-waits ordering (v3, patch 0016) fixes AO's one-frame lag in the lab but is off (one residual dip, a
  device loss at the castle spot).
- Open: #128 intro speed (not started), #138 gray close-LOD bushes (candidate patch 0018 in `nx2navi.new`, A/B
  untested), AO flicker (above), the mesh-stage c0 overflow upstream (worked around by 0006).
- Flatpak build kit for the Steam Deck (`flatpak/`, private CI artifact), untested on a Deck.
- Blocker since 2026-11-09 00:00: every lab replay loses the GPU device about 26 s in, with the stock binary too;
  the kernel driver looks degraded after the earlier resets. Needs a dmesg check and probably a reboot; no replays,
  swaps or live tests until then.

## What was verified

- Build: the whole pipeline in the Manager's container (lift 297,414 functions, 318 MB binary), rebuilds of
  `nx2navi.new` from the `build` branch with `ninja -f build/v111/build.new.ninja`.
- Play on the host: hours of play across Kokiri Forest, the Deku Tree, Hyrule Field and the castle with pad, HDR10,
  60 fps outdoors (240 Hz panel, frame limit by the game), logs in `build/v111/logs/play-*.log`.
- Lab (container, RX 6900 XT through `/dev/dri` and the gpu-display compositor) until 2026-11-08 23:58: replays of
  Cal's recordings and slot save to fixed frames, with dumps, shots, core validation (two VUIDs, NOTES "Validation
  sweep") and A/B of patches 0004, 0008-0010, 0016.
- Not verified: patches 0018 and 0019 (built, not swapped), the Flatpak kit on a Deck, fmz-pow's removal.

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
  scene), dropping the oldest past the cap. Built into `nx2navi.new`, not swapped, untested; suggested first value 3072 (#132).
- `0018-vk_pipeline-map-the-RGBX-sRGB-and-BGRX-vertex-format.patch`: **candidate, not yet A/B tested** (#138 gray bushes).
  A vertex attribute whose NVN format had no table entry (RGBX8/16/32, 8-bit sRGB, BGRX8) read the zero binding
  (0, 0, 0, 1) silently, collapsing any shape with such an attribute; they now read as the 4-component format, and an
  attribute still without a mapping is logged once (`vk_pipeline: vertex attribute ... without a vertex format`). The
  lab replays of 2026-11-09 lost the GPU ~26 s into every run from 00:00 on (innocent context, time-based, also with
  the stock binary and RADV syncshaders), so the near-bush A/B (castle courtyard, Cal's slot save, frame 1500) is still
  open; `build/v111/nx2navi.new` carries 0017+0018 and was **not** swapped in.

## Mark this moment

When a glitch shows, mark it with one of: **F9** (game window focused), **L3+R3 held 0.5 s** (both stick clicks;
hidden from the game while both are down), or `touch build/v111/mark.req` from any tool. Each mark:

- logs `mark N at present P (why)` in the play log;
- saves that present as `logs/shot-<P>.png` (also on HDR10: native HDR's PQ picture is decoded to sRGB);
- touches `dump.req` when the game runs with `NX2NAVI_DUMP_REQ=1`, so the next frame is dumped;
- with `NX2NAVI_MARK_RING=1`, writes the last 30 presents as 320x180 PNGs to `logs/mark-<N>/` (a GPU blit per present
  into a 7 MB host-visible ring, the flight recorder's; written on a background thread). Off by default.

Settings: `NX2NAVI_MARK_CHORD` (pad buttons joined by `+`: south east west north lstick rstick l r zl zr start back
dpad_*; `off` for none; default `lstick+rstick`), `NX2NAVI_MARK_HOLD_MS` (500).

yakin quick-menu item (add it to the `[menu] items` of your yakin config yourself), for a mark without the chord:

```toml
{ label = "Mark glitch", icon = "screenshot", target = "desktop:spawn:touch /home/purplg/claude/nx2navi/NX2navi/build/v111/mark.req" },
```

## lab-run debug options

Both are opt-in environment variables for `tools/lab-run` (see its header):

- `LAB_VALIDATE=1`: Khronos validation layer from nixpkgs plus synchronization validation. Messages go to `.lab/<label>/validation.log`, at most 3 per message ID. Slow.
  `LAB_VALIDATE=core` drops synchronization validation. Known (2026-11-09): sync validation, and core checks together with
  `check_shaders`, stall the game at boot (every thread in a futex wait); lab-run leaves check_shaders off
  (`LAB_VALIDATE_SHADERS=true` turns it on), so only `LAB_VALIDATE=core` gets through. `LAB_VALIDATE_THREADS`, `LAB_VALIDATE_FGL`,
  `LAB_VALIDATE_SETTINGS="key=value;..."` help to bisect the layer; `LAB_EXE=nx2navi.new` replays another binary in the game dir.
- `LAB_HANG=1`: `RADV_DEBUG=nogpl,hang`; the `radv_dumps_*` hang reports land in `.lab/<label>/hang`. Known: replays to frame 1100 hit `radv: GPU hang detected`, then radv crashes
  (libvulkan_radeon.so+0xfae0c) before writing a report.

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
`NX2NAVI_PIPE_SKIP=any`, `NX2NAVI_HDR=native`, `NX2NAVI_REPLAY_ASYNC=1`, `NX2NAVI_VK_RECORDER=1`, each overridable.
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
