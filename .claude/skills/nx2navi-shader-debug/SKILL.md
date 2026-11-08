---
name: nx2navi-shader-debug
description: Troubleshoot NX2navi (Zelda OoT Switch 2 recompilation) rendering bugs - black or white pictures, NaN or inf in images, fog, haze or lighting glitches - and run shader A/B tests (skip, patch or guard a shader and compare). Use for any NX2navi shader, translator, shadow-sync or hot-reload investigation.
---

# NX2navi rendering and shader debugging

Tooling lives in `~/claude/nx2navi` (tools/, patches/, justfile). The full log of the first investigation is
`NOTES-fog-nan.md`: read it before repeating anything. Game dir: `NX2navi/build/v111` (logs/, shader-cache/, dump-*).

## Method, in order

1. **Live hot-reload first.** Ask Cal to run `NX2NAVI_SHADER_RELOAD=1 just play`, standing at a fixed spot (indoors
   or a still outdoor scene). Edit the cache `<key>.spv` with temp file + rename (never in-place writes), back up the
   original in `build/v111/reload-bak/` first. The game logs `vk_pipeline: reload <key16> ok|failed` within about one
   frame. Take a picture by touching `build/v111/shot.req` (writes `logs/shot-<n>.png`). One edit costs about 15 s.
   `tools/reload-feed` sums reloads into the feed. Restore every touched file from the backup when done.
2. **Lab replays only when no game is running.** `tools/lab-run [--show] <recording> <dump-frame> <label> [KEY=VALUE...]`
   (flock on /tmp/nx2navi-lab.lock; refuses if a game runs). `tools/lab-when <label> <regex>` gives the time of a log
   line. Caveat: replays drift. The same recording landed in three different scenes at frame 1900, in the pause menu,
   or indoors after save data changed. Check the scene at the dump frame before trusting any A/B. Prefer an early
   frame, or a fresh recording from Cal's current save.
3. **Dumps.** `NX2NAVI_DUMP=<frame>` (counts presents) with `NX2NAVI_DUMP_DIR`, `NX2NAVI_DUMP_UBO=n` (constants) and
   `NX2NAVI_DUMP_BUF=addr:size` (one range). Read `images.txt` for per-image NaN counts and `passes.txt` for
   which pass writes what. Note: NClamp/NMax in shaders turns NaN into 0, so "no NaN in the frame" can still mean a
   NaN was silently clamped to black. Dump SPIR-V is raw translator output, not the cache file (names are not its sha256);
   match by size + cmp.
4. **Narrow the culprit.**
   - `NX2NAVI_SKIP_SHADERS=<hash,...>` drops shaders: which one makes the artefact appear or vanish.
   - Bisect the drawn shaders by halves with a post-pass (apply a transform to half of the frame's shaders, look,
     recurse), then one site at a time inside the last shader.
   - **NaN guard vs inf guard** tells which you have: guard the suspect input with NMax (NaN to 0) and separately
     with a clamp for inf. If only the NaN guard lights the scene, it is NaN. (tools/nan-guard.py guards image
     writes; cas-nan-guard.py guards float atomic-add CAS loops.)
5. **Trace the NaN to its data source before blaming the translator.** Follow the operand back through vs outputs,
   storage buffers and writers (`passes.txt` "written"). `NX2NAVI_WATCH=addr:size` logs every GPU and CPU touch of a
   guest range, so you can see whether the CPU's writes reach the shadow copy (memory sync gap).
6. **Write the finding to the log** and only then fix: runtime patch on branch `build`, or a translator change.

## What was learned (do not repeat)

- Root cause of the black fog and white-out lighting: **runtime shadow sync** (build f33ed65, patches/0004). The
  game zeroes the sky-SH block (0x25a4c7f00) on the CPU each frame; the sync skipped the range because the same part
  rewrites it, so stale sums accumulated (white-out) and one NaN stuck forever (black).
- **Not FMZ.** The game's shaders are sm86 and none uses FMZ (0 lowering failures over 44,156 shaders;
  patches/0002 is a no-op). fmz-pow.py, fmz-all.py, nan-guard.py, cas-nan-guard.py and cas-reset.py only masked the
  NaN. They are stopgaps: never ship them, restore the .orig files, and rerun after `just shaders` only if a stopgap is
  intentionally wanted.
- Dead ends: `NX2NAVI_MEMORY=import` (no change), `RADV_PERFTEST=cswave32` (no change), ACO_DEBUG noopt (not an ACO
  optimisation), `NX2NAVI_SHADOW=0` (device lost), blaming the PRMT patch, the mesh path, constants c3/c4/c5, the
  probe grid headers, the mist card shader 3a6b76e4 (skipping it changes nothing), tonemap UBO values.
- A fresh shader cache renders black on a runtime with the sync bug; that is the bug, not a translator regression.
- A write-back storm (pointer-bound SSBO with size 0 noted as "to end of pool") is a separate, fixed bug
  (patches/0001, 0008). Brightening from stale GPU bytes copied over CPU writes is the related hazard.

## Rules

- **Never write the live shader cache outside the reload loop** (backed up, temp + rename, restored after). Use a
  private copy of the cache for anything else. **No hardlinked build copies** (`cp -al` of the cache or build dir:
  an in-place write corrupts both).
- **Builds renice the process group to 19** (the container's base niceness is -4), so a compile never starves Cal's
  running game. Hold builds and agents while Cal games.
- **Private patches stay on branch `build`** of `NX2navi` and are never pushed or published (the license forbids it).
  After `just update`, rebase `build`. Keep `patches/` copies in step.
- **Feed lines.** Write short lines to the screensaver feed `~/claude/.services/screensavers/feeds/nx2navi-lab.log`:
  `search:`, `step:`, `suspect k/N:`, `learned:`, `result:`. Do this silently. **Never mention the screensaver to
  Cal** unless he asks.
- **Profiles: Cal runs host perf.** Give him Nushell commands, e.g. `nix build nixpkgs#perf --no-link --print-out-paths`
  and then, since sudo needs the full path, `sudo <out>/bin/perf record -g -o ~/claude/nx2navi/perf.data -p (pidof nx2navi)`
  followed by `sudo chown $env.USER ~/claude/nx2navi/perf.data`. Test the syntax with `nu -c` first.
- One step per message to Cal, with the expected outcome stated. Self-verify (logs, dumps, lab) before asking him.
- No Claude trailers (Co-Authored-By, Claude-Session) on any commit or PR here.
