---
name: nx2navi-lab-start
description: Start here for any NX2navi / Zelda (Ocarina of Time, Switch 2 recomp) task - reproducing a bug, perf or rendering work, playtests, lab runs. Lists the lab's ready-made tools (teleport by save edit, scenarios, recipes, burst capture, dumps) so you set up your own scenario instead of replaying old captures.
---

# NX2navi lab: first steps

Developer and lab skill. Just installing and playing on a new machine: use `nx2navi-setup`.

Read before anything else: `~/claude/nx2navi/README.md`, the ARCHITECTURE.md sections you touch, `.lab/BOARD.md`, any AGENTS.md. Check upstream (fetch) at the start.

## Set up your own scenario (do this, don't hunt old captures)
- **Teleport:** `tools/warp-save <profile-copy> scene=<name> [pos=x,y,z] [face=<deg>] [age=child|adult] [entrance=..] [gd=<recipe>]` rewrites progress.sav in a profile COPY so Link loads there. Scene names: `tools/scenes.toml`. `yaw=` is ignored by the spawn; use `face=`.
- **Recipes:** a mark or dump writes `recipe.dbg` (scene, position, facing, game data). `tools/recipe <name>` reads `tools/scenarios/<name>.dbg` (see `tools/scenarios/README`). Ready scenarios include field-mid-standing, field-west-standing, field-fly, field-run-route, forest-temple-standing.
- **Time of day:** `time=` is NOT supported yet in warp-save. If your bug depends on daylight/night, add it (game data or save field, default unchanged) instead of settling for whatever time a save has.
- `tools/scenario` manages the regression/starting-point collection (`scenarios/README.md`).

## Running
- NEVER run device-loss/hang repros on the desktop without asking Cal first: a GPU hang resets his whole card (2026-11-16).
- Before any GPU job: `~/claude/.services/locks/games-running desktop`; if a game runs, CPU only (`taskset -c 12-15,28-31`, -j8). GPU work under `flock ~/claude/.services/locks/gpu.lock`; `tools/lab-run` only. Offscreen only, never Cal's display, no sound.
- Never the live profile: `tools/not-live` refuses it unless `NX2NAVI_LIVE_PROFILE_OK=1` (don't set it).
- Builds go to named variants `build/v111/nx2navi.<name>`. One branch, `build`. Default `just play` = `runs/carry1.sh` (exe `nx2navi.squash1`, translator `build/xlate-701e7ce`); `NX2navi/build` is a symlink into `~/claude/.build/nx2navi/build`.

## Capturing
- Per-frame screenshots drop fps to ~10 and can hide timing bugs: prefer bursts (`touch build/v111/mark.req`, burst-* tools) or cheap metrics.
- Full GPU dumps: `NX2NAVI_DUMP_REQ=1` run, then F9 / dump.req; the dump folder gets recipe.dbg.
- Replays drift (enemies move); use a fixed camera and metrics that ignore actors.

## Results
- Tag every finding with the build line (entry, exe, commit). ≥3 runs per arm with the spread; controlled A/B; full ini for device A/B.
- Fixes ship behind an env knob, default off (Cal judges defaults); note uncertain ones in UNCERTAIN.md.
- Post suspect k/N, learned:, result: lines to the screensaver feed. Correct ARCHITECTURE.md when a finding contradicts it.
- For shader/NaN/fog issues also load the nx2navi-shader-debug skill.
