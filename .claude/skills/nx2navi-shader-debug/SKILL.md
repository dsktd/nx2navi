---
name: nx2navi-shader-debug
description: Troubleshoot NX2navi (Zelda OoT Switch 2 recompilation) rendering bugs - black or white pictures, NaN or inf in images, fog, haze or lighting glitches - and run shader A/B tests (skip, patch or guard a shader and compare). Use for any NX2navi shader, translator, shadow-sync or hot-reload investigation.
---

# NX2navi rendering and shader debugging

Tooling lives in `~/claude/nx2navi` (tools/, patches/, justfile; problem -> tool table in ARCHITECTURE.md section 11 "Tools"; `NX2NAVI_FLIGHT=1` + `just flight` for pictures of a spike). The full log of the first investigation is
`NOTES-fog-nan.md`: read it before repeating anything. How the pieces fit: `ARCHITECTURE.md` section 7 (shaders,
lowering bugs, invalid SPIR-V, window origin), section 6 "Texture cache" (wrong or missing textures), section 11
(dump options, picks, lavapipe runs). Game dir: `NX2navi/build/v111` (logs/, shader-cache/, dump-*).

## Method, in order

0. **Name the build line** (`entry= exe= commit=`, log's first `[host] build:` line or dump `build.txt`) and the
   translator identity (`nx2navi_xlate.id` in the translator dir, logged at boot). Check `/dev/udmabuf` took: the log
   must say `mem: guest memory is a memfd's` (else `mem: dma-buf imports off` = shadow storage, numbers and sync bugs
   differ from Cal's play).
1. **Live hot-reload first** (Cal's game, standing still). `NX2NAVI_SHADER_RELOAD=1 just play`; edit cache
   `<key>.spv` by temp + rename after backing up to `build/v111/reload-bak/`; wait for `vk_pipeline: reload <key16>
   ok|failed`; touch `build/v111/shot.req` -> `logs/shot-<n>.png`. ~15 s an edit. Hands-free: `tools/ab --region
   X,Y,W,H [--dump DIR|--pick|--fs h,h]` (kill/zero variants per fragment shader, base shots around each give the
   noise floor, ranked table; `tools/ab --restore BAKDIR` after a killed run). `tools/reload-feed` sums reloads.
2. **Lab replays only when no game runs** (newest `logs/play-*.log` untouched for 3 min; board GPU queue).
   `tools/lab-run [--show] [--warp '<spec>'] <recording> <dump-frame> <label> [KEY=VALUE...]` (`LAB_EXE=nx2navi.<v>`,
   `LAB_VALIDATE=1`, `LAB_RENDERDOC=<f>`, `LAB_HANG=1`, `LAB_NODUMP=1`, `LAB_SOFT=1` lavapipe off-GPU). Spots:
   capture cells (`tools/cap-cell`, `NX2NAVI_CAPTURE_REPLAY`) or recipes (`tools/scenarios/*.dbg`) instead of
   boot-timed recordings; check the scene at the dump frame. A/B: one run with the knob `ab` + `NX2NAVI_AB=5`
   (ABBA, `tools/ab-cell`, null knob beside it; only `RT_KNOB_ON` knobs switch live), or interleaved runs x3.
3. **Fixed measuring window.** Numbers only from a standing window of game time (`tools/frame-window LOG a-b`,
   e.g. f2663 1800-3000), never the dump frame's perf window (~280 ms) nor the exit stall. An armed dump turns off
   replay-worker groups and the early tail: perf A/Bs use `LAB_NODUMP=1`. `NX2NAVI_FIXED_STEP=60` steadies the
   script clock, not loads: >=3 runs, medians, spread; moving windows are indicative only.
4. **Dumps + NaN counts.** `NX2NAVI_DUMP=<present>` (+`_DIR`, `_UBO=n`, `_BUF=addr:size`): `images.txt` per-image
   NaN/inf counts, `passes.txt` writers, `mesh.txt`. NClamp/NMax turn NaN into 0: no NaN can still mean clamped black.
   Live: `NX2NAVI_DUMP_REQ=1` + `dump.req`, `pick.req`/F5 (`NX2NAVI_WATCH_REQ=1`) for draws under the centre pixel.
   Dump SPIR-V is raw translator output; match cache files by size + cmp.
5. **Narrow the culprit.** `NX2NAVI_SKIP_SHADERS=<hash,...>` bisect: halve the frame's drawn shaders (from
   passes.txt) until one toggles the artefact, then one site at a time inside it. SPIR-V post-passes on a private
   cache copy (`spirv-val` after each): `tools/nan-guard.py` (image writes), `cas-nan-guard.py` (float CAS),
   `txq-array-fix.py` (layer-count query), `ab --variants-only SPV kill|zero`. NaN guard (NMax) vs inf clamp tells
   which you have. Stopgaps only: never ship them.
6. **Trace to the data source before blaming the translator.** Follow operands through vs outputs, storage buffers
   and writers; `NX2NAVI_WATCH=addr:size` logs every GPU/CPU touch (shadow sync gap). Lowering suspects: `just xdiff`.
7. **Report.** Feed lines (`step:`, `suspect k/N:`, `learned:`, `result:`) to
   `~/claude/.services/screensavers/feeds/nx2navi-lab.log`, then ARCHITECTURE.md, then fix (knob, default old).

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

## Known pitfalls

- **Bit-position lowering bugs.** `AmpereLowering.cs` re-encodes SM86 as Maxwell; I2F had its signed flag in bit 12
  instead of 13 (all signed int-to-float unsigned; fix 0064, `tests/i2f_sign_check.py`). Geometry blown up only where
  values are negative points here. A translator fix re-keys the whole cache: use `just try-i2f`'s own caches.
- **Mesa-rejected SPIR-V** crashes RADV (NULL in `radv_shader_spirv_to_nir`): run `spirv-val`; known case is a
  layer-count size query on a default-2D texture (`tools/txq-array-fix.py`).
- **Wrong-size or blank texture is often the texture cache**, not the shader: `slot_resolve` follows another
  descriptor at the address (#172 seam, `TEX_DESC_STRICT`) or applies the stale/gone rule (#149/#169, `TEX_STALE_LIVE`).
- **Translator identity re-keys the whole cache** (#149). A new translator recompiles every shader; upstream's
  carry (`identities.txt` in the cache folder) serves old translations until each is retranslated, so an old
  translator's bugs can linger. Pool length: translators before upstream 2388f1f clamp texture handles to 32767
  (Ocarina's pool has 33068): slots >= 32768 draw slot 32767's image = see-through ground after an area load. Check
  the id against `build/xlate-701e7ce` (7b7bde78, `runs/xl701.sh`); upstream b04e7c8 logs old-length carries,
  f1a2a64 refuses packaging a mismatched translator. Never compare caches of two identities as one.
- **Hot-reload bisects need a fixed camera**; a moved view voids pixel metrics.
- **lavapipe** (`LAB_SOFT=1`) has subgroup size 8, not 32: no verdict on subgroup-dependent shaders there.
- `gpu_owned/written-since` in passes.txt ignores compute image stores.

## Rules

- **Cite the build.** Every finding, tracker note and report about a symptom names the build line it was seen on
  (`entry= exe= commit=` from the log's first `[host] build:` line, or the dump's `build.txt`; ARCHITECTURE.md 11).
  Never compare symptoms across two different build lines without saying so.
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
- Durable findings go into `ARCHITECTURE.md` (the matching section) before you finish, not only into the feed.
