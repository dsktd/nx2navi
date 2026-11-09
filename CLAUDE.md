# nx2navi: agent guide

This repo builds and runs NX2navi on Cal's Arch desktop through Nix. NX2navi is a static recompilation of Zelda: Ocarina of Time (Switch 2, version 1.1.1) to x86-64 with Vulkan. The GPU is an RX 6900 XT on RADV, and the desktop is Niri with a 240 Hz BenQ QD-OLED.

Read `README.md` first: build steps, workarounds, private patches. The investigation log is in `NOTES-fog-nan.md`. To debug rendering, load the skill `.claude/skills/nx2navi-shader-debug/SKILL.md`.

## Layout

- `NX2navi/` is a worktree of upstream (`tangerineturtle1/NX2navi`) on the local branch **`build`**. It is gitignored here and is **never pushed**.
- `build/v111/` holds the game binary, the shader and pipeline caches, `profile/` with Cal's saves, and `logs/` with `play-*.log` and `input-*.txt` recordings.
- `flake.nix`, `justfile`, `build-linux.py` and `runtime-linux/` are our build glue. We edit these freely.
- `patches/NNNN-*.patch` are copies of the private commits on `build`, each with a README entry.
- `tools/` holds the lab tooling: `lab-run` replays, `reload-feed`, and the obsolete NaN stopgaps (see README "Obsolete stopgaps").

## Hard rules

- **License.** Upstream's additions forbid redistribution. Changes to upstream code are private commits on `build`, copied to `patches/`. This repo's remote is the **private** `dsktd/nx2navi`. Never make it public, and never push `build`.
- **Cal's game runs on the host,** so container `/proc` can't see it. Treat it as running while the newest `build/v111/logs/play-*.log` was written less than 2 minutes ago.
  - **No `lab-run` replays while he plays.** A GPU fault in a replay resets the GPU and crashes his game; `lab-run` refuses in that case.
  - Live work in his game is allowed when it was started with `NX2NAVI_SHADER_RELOAD=1`:
    - shader edits through hot-reload: write a temp file and rename it, keep backups in `build/v111/reload-bak/`, restore failed tests
    - screenshots: `touch build/v111/shot.req`, and the shot lands in `logs/shot-N.png` (not yet working on HDR10 swapchains)
    - dumps: `dump.req`, with `NX2NAVI_DUMP_REQ=1`
- **Builds are allowed while he plays.** Renice the process group to 19; the container's base niceness is -4, so `nice -n 19` only reaches 15. Build to `build/v111/nx2navi.new` and swap the file whole (rename). Never overwrite the running binary.
- **Never write to `profile/`.** Copy it for tests; `NX2NAVI_PROFILE_DIR` needs an absolute path (Nushell passes `~` through literally). Never write to the live shader cache except through the reload loop.
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

- `just play` runs the game with the defaults: `PIPE_SKIP=any`, `HDR=native`, `REPLAY_ASYNC=1`, `VK_RECORDER=1`. Any of them can be overridden from the environment.
- After `just update` (an upstream pull), rebase `build` and rebuild with `just xlate game shaders`, then re-check the private patches.
- `just shaders` re-runs `fmzpow`, a pow NaN stopgap that is probably obsolete since `f33ed65` but not yet proven so.
- State of record: the tracker in `dsktd/context` (#128 is 240 fps, #132 is performance), plus git history and the notes.
