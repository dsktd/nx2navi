---
name: nx2navi-setup
description: Get NX2navi (the Zelda Ocarina of Time Switch 2 recompilation) installed and playing well on a new Linux machine from a .nup - machine check, `just setup`, first launch, first-run failures, then tuning toward a stable 60 fps. For players; lab and development work use nx2navi-lab-start.
---

# NX2navi: set up and play

For playing. Developing, measuring or debugging the build: use `nx2navi-lab-start` instead.
Knowledge lives in `ARCHITECTURE.md`, `README.md` and `SYMPTOMS.md`; this skill is the procedure and links there.
"(unverified)" marks steps nobody has run on a second machine yet.

## 1. Get it running

1. **Machine check.**
   - Linux on Wayland (no X11 path is supported). Nix with flakes (every tool comes from the flake, `nix develop`).
   - GPU: AMD/Intel through Mesa (default) or NVIDIA (`NX2NAVI_GPU=nvidia`, README "GPU"). Check the driver with
     `nix develop ~/claude/nx2navi --command nixVulkanIntel vulkaninfo --summary` (Mesa version and the RADV device).
     Tested only on an RX 6900 XT (RADV) and the Steam Deck OLED.
   - Free disk: `just setup` prints the need (~45 GB: extract ~30 GB, game build and caches ~15 GB).
   - `/dev/udmabuf` read-write (else shadow copies, ~20% slower): `just launcher --check` prints this and the other
     start checks (README "Launcher").
2. **Build everything:** `just setup /path/game.nup` (or `NX2NAVI_NUP`). It checks the .nup is OoT 1.1.1, then
   worktree, config, venvs, extract, translators, game, exe name `nx2navi.squash1`, shader caches; a re-run skips
   finished steps. The shader step opens a window and takes long: run it from the desktop session.
3. **Play:** `just play`. Logs go to `NX2navi/build/v111/logs/play-*.log`; the first `[host] build:` line names the build.

### First-run failures

| what you see                                         | what it is                                                                  | do                                                                                                                  |
| ---------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `setup: just check rejects`                          | not a 1.1.1 dump, or a broken file                                          | get a 1.1.1 .nup                                                                                                    |
| black picture, overlay works                         | pipelines skipped while they build, or a translator without its patches     | keep `NX2NAVI_PIPE_SKIP=any` (README "RADV workaround"); rebuild with `just xlate` (README "Translator patches")    |
| black picture, log says the translator was not found | `NX2NAVI_XLATE` must be an absolute path (unverified as a separate failure) | use `just play`, which passes `runs/xl701.sh`'s absolute path                                                       |
| crash in `libvulkan_radeon.so` at start              | RADV GPL bug                                                                | keep `RADV_DEBUG=nogpl` (set by the justfile; README "RADV workaround")                                             |
| stutter in every new area, first hour                | shaders and pipelines compile on first sight                                | let `just setup`'s shader step finish; it fills `shader-cache-rebase` and the pipeline cache (ARCHITECTURE.md 7)    |
| "GPU device was lost"                                | GPU memory pressure or a known bug                                          | SYMPTOMS.md "Occasional GPU device loss"; on a Deck ARCHITECTURE.md 11 "Steam Deck OLED" (memory is the first wall) |
| black fog / white-out light outdoors                 | shadow sync bug, fixed in squash1                                           | check the build line names `squash1`; `.claude/skills/nx2navi-shader-debug` if it persists                          |
| see-through ground after an area load                | old translator (texture pool 32768)                                         | translator must be `build/xlate-701e7ce` (id 7b7bde78): `just xlate-pin`                                            |
| `just play` runs another exe                         | a run script names an exe you do not have                                   | plain `just play` = `runs/carry1.sh`; README "Consolidation of the justfile and runs/"                              |

## 2. Get it running well

- **Default run, keep it:** `runs/carry1.sh` on `nx2navi.squash1` with translator 701e7ce and
  `NX2NAVI_SHADER_CARRY_POOL=1` (README "Private local patches", 0126). Async replay stays off: it flickers
  (`NX2NAVI_REPLAY_ASYNC=0`, Cal 2026-11-18).
- **Target is a stable 60.** The game steps by vsync; above 60 game speed is held by the carried fixes, but lab
  scenes run 55-61 fps (ARCHITECTURE.md 8 "Timing"; SYMPTOMS.md "240 fps target").
- **CPU pinning:** `NX2NAVI_CPUS=auto` (default) keeps the game on one L3 domain on multi-CCD CPUs; `NX2NAVI_CPUS=off`
  to compare (UNCERTAIN.md; justfile `play`).
- **Warm caches:** second and later sessions are smoother; never delete `shader-cache-rebase` or
  `pipeline-cache-rebase*.bin`. A translator change re-keys the whole cache (ARCHITECTURE.md 7).
- **AMD/RADV:** `RADV_DEBUG=nogpl`, `NX2NAVI_PIPE_SKIP=any` (README "RADV workaround"); CPU governor/EPP on
  performance helps (launcher check).
- **Steam Deck:** different path (Flatpak kit, device profile 40 fps cap, memory limits): README "Steam Deck" and
  ARCHITECTURE.md 11 "Steam Deck OLED". Build on a desktop, never on the Deck.

### Which problem do I have

1. Read the log's `[host] build:` line: is it squash1 with xlate 7b7bde78? If not, fix the run first.
2. `mem: guest memory is a memfd's` in the log? If `mem: dma-buf imports off`, fix `/dev/udmabuf` first.
3. Slow everywhere: CPU pinning, governor, udmabuf. Slow only on first visits: cache warm-up. Hitches on area
   entry: known (SYMPTOMS.md "Scene-load freeze"). Wrong picture: SYMPTOMS.md row, then the shader-debug skill.
4. Per-build summary of a log: `just logstat <log>`.
