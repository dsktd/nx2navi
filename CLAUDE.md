# nx2navi: agent guide

This repo builds and runs NX2navi on Cal's Arch desktop through Nix. NX2navi is a static recompilation of Zelda: Ocarina of Time (Switch 2, version 1.1.1) to x86-64 with Vulkan. The GPU is an RX 6900 XT on RADV, and the desktop is Niri with a 240 Hz BenQ QD-OLED.

Read `README.md` first: build steps, workarounds, private patches. The investigation log is in `NOTES-fog-nan.md`. To debug rendering, load the skill `.claude/skills/nx2navi-shader-debug/SKILL.md`. How it all works, plus pitfalls and current recipes: `ARCHITECTURE.md`.

Before you finish, add durable findings (facts and where in the code) to the matching section of `ARCHITECTURE.md`, not just the feed; correct it where a finding contradicts it.

Shared lab board `~/claude/nx2navi/.lab/BOARD.md` (scratch, not committed): read it at start and before each build or GPU run; add your line under "Working now" (task, exe/files you change, since) when starting, update it at each milestone, remove it when done. If someone already changes the same file (e.g. `runtime/vk_texture.c`), coordinate there ("after X") instead of editing in parallel. Claim the next patch number on the board before writing it. Note GPU lock holder/waiters under "GPU queue"; add dated one-liners to "Fresh findings" (newest first, trim to ~40).

Results record (Cal, 2026-11-12). Every verified measurement goes into `results.tsv` and every exe into `builds.tsv`; symptoms go into `SYMPTOMS.md`. `tools/ab-cell` and `tools/load-cell` append their rows themselves and refuse an exe with no `builds.tsv` row: right after a build run `tools/builds-add <exe> <commit> <parent-exe> xlate=<dir/id12> wt=<worktree> [run=runs/x.sh]` (computes the patches contained and the change vs the parent). Charts: http://127.0.0.1:8080/results/ (service `results`). Iteration = one targeted ab-cell/load-cell for the metric you work on; candidate builds are judged by the fixed suite (`just suite <exe>`, `tools/nightly`) and a recommendation waits for a nightly.

## Layout

- `NX2navi/` is a worktree of upstream (`tangerineturtle1/NX2navi`) on the local branch **`build`**. It is gitignored here and is **never pushed**.
- `build/v111/` holds the game binary, the shader and pipeline caches, `profile/` with Cal's saves, and `logs/` with `play-*.log` and `input-*.txt` recordings.
- `flake.nix`, `justfile`, `build-linux.py` and `runtime-linux/` are our build glue. We edit these freely.
- `patches/NNNN-*.patch` are copies of the private commits on `build`, each with a README entry.
- `tools/` holds the lab tooling: `lab-run` replays, `logstat` (`just logstat A [B]`: per-build log summary and A/B diff), `reload-feed`, and the obsolete NaN stopgaps (see README "Obsolete stopgaps").
- `NX2navi/tools/` is upstream's tooling. Reach for it before writing new scripts (Cal, 2026-11-11): profiling `perf_summary.py`, `prof_report.py`, `crit_path.py`, `flight_view.py`, `spin_waits.py`, `ab_summary.py`, `pgo.py`; shaders `shader_census.py`, `shader_list.py`, `xlate_smoke.py`, `check_isa.py`; game data `extract.py`, `romfs_index.py`, `make_romfs_patches.py` (zstd dictionaries), `exefs_patches.py`, `cheats.py`. Recipes: `just perf-summary|ab|crit|flight` (knobs in ARCHITECTURE.md section 11 "Tools"). Say in reports which ones you used.

## Hard rules

- **License.** Upstream's additions forbid redistribution. Changes to upstream code are private commits on `build`, copied to `patches/`. This repo's remote is the **private** `dsktd/nx2navi`. Never make it public, and never push `build`.
- **Cal's game runs on the host,** so container `/proc` can't see it. Treat it as running while the newest `build/v111/logs/play-*.log` was written less than 2 minutes ago.
  - **One GPU job at a time.** Every GPU use (replays, RenderDoc replays, captures) takes the lab lock `/tmp/nx2navi-lab.lock`; two at once exhausted VRAM and lost the device (2026-11-09). `lab-run` also waits for 10 GiB free VRAM.
  - **Software runs may overlap Cal's play; GPU runs may not.** `LAB_SOFT=1 tools/lab-run ...` renders on Mesa lavapipe (llvmpipe), only lavapipe's ICD visible, pinned to cores 12-15,28-31, about 6 fps at render scale 50: good for start checks (no FATAL) and a shot, not for perf numbers or GPU-specific bugs (lavapipe's subgroup size is 8, not 32).
  - **No `lab-run` replays while he plays.** A GPU fault in a replay resets the GPU and crashes his game; `lab-run` refuses in that case.
  - Live work in his game is allowed when it was started with `NX2NAVI_SHADER_RELOAD=1`:
    - shader edits through hot-reload: write a temp file and rename it, keep backups in `build/v111/reload-bak/`, restore failed tests
    - screenshots: `touch build/v111/shot.req`, and the shot lands in `logs/shot-N.png` (HDR10 too since patch 0015); marks: `mark.req`, F9 or L3+R3 (README "Mark this moment")
    - dumps: `dump.req`, with `NX2NAVI_DUMP_REQ=1`
- **Builds are allowed while he plays.** Renice the process group to 19; the container's base niceness is -4, so `nice -n 19` only reaches 15. Build to `build/v111/nx2navi.new` and swap the file whole (rename). Never overwrite the running binary.
- **Saves.** Agents may use the live `profile/` (Cal, 2026-11-09): `lab-run` snapshots `save*` before a run and restores them after, so his latest save stays as he left it. A separate copy still works; `NX2NAVI_PROFILE_DIR` needs an absolute path (Nushell passes `~` through literally). Never write to the live shader cache except through the reload loop.
- **No hardlinked copies of build trees.** Use reflink or plain copies.
- **Commits:** only your own files (`git add <paths>`, never `-a`), plain messages, **no Co-Authored-By or Claude-Session trailers**. Push with:
  `GH_TOKEN=$(tr -d '\n' < ~/.config/gh/dsktd.token) git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push`
- **Never file upstream issues** (Cal's decision). `upstream-issue-c0-mesh.md` is a draft that is kept only.
- **Host commands for Cal** are given in Nushell. He runs `perf` on the host (sudo needs the full path from `nix build nixpkgs#perf`; then `chown` the output).

## Progress feed

Long investigations report to `~/claude/.services/screensavers/feeds/nx2navi-lab.log`. Line types:

- `search: …`
- `step: …`, before anything that takes over 20 s
- `suspect k/N <name> <id>: testing|cleared|CULPRIT|unclear - …`
- `learned: <plain sentence>`
- `result: …`

`lab-run` adds its own `run`/`done` lines. Never mention the screensaver to Cal.

## Day-to-day

- `just play` runs the game with the defaults: `PIPE_SKIP=any`, `HDR=native`, `REPLAY_ASYNC=1`, `VK_RECORDER=1`, `TEX_RELEASED_MIB=3072`. Any of them can be overridden from the environment.
- After `just update` (an upstream pull), rebase `build` and rebuild with `just xlate game shaders`, then re-check the private patches.
- `just shaders` re-runs `fmzpow`, a pow NaN stopgap that is probably obsolete since `f33ed65` but not yet proven so.
- State of record: the tracker in `dsktd/context` (#128 is 240 fps, #132 is performance), plus git history and the notes.
