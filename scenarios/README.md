# Scenarios

Cal's saves and input recordings kept as fixed starting points (private data: this repo stays private). One directory
per scenario:

- `scenario.toml`: `name`, `tests`, `grade` (`regression` or `start`), `tracker`, `source` (session, marks, why this
  save), `frame` (lab-run's dump frame; 999999 = run to `timeout`), `timeout` (s), `env` (knobs), optional `taskset`,
  `pipeline_cache` (`copy` of the live cache, default, or `empty`), and `[[check]]` entries:
  - `exit`: no FATAL line, the dump frame reached;
  - `picture`: `ref` (a PNG in `ref/`) against lab-run's `final.png`, RMSE at 320x180 at most `max_rmse`;
  - `window`: `ticks = [t0, t1]` of game time through `tools/frame-window`, `fps_min`, `p99_max`, `replay_max`;
  - `count`: lines matching `regex` in run.log at most `max`.
  `advisory = true` reports a check without failing it.
- `input.txt.xz`: the recording; `save.tar.xz`: `save`, `save-tx`, `save-backup` it starts from; `ref/`: reference
  frames (lab finals or Cal's mark shots, 640x360). Never a frame of the public-video references, nothing from romfs.

`regression` scenarios replay only title-menu presses, or are measured only in a standing-still window, so they land in
the same place each run. `start` scenarios drift once Link moves (#145, the game steps by the wall clock): they get you
near a bug, their numbers and pictures are indicative.

Run: `just scenario <name>...`, `just regress [names...]` (exit 1 on a failure, 2 if Cal was playing for
`SCENARIO_WAIT_MIN`), `--dry` for the plan. `NX2NAVI_EXE=<variant>` judges `build/v111/nx2navi.<variant>`. Each run
stages into `.lab/scenario-stage/<name>/`, and lab-run builds a scratch profile from the bundle in `.lab/scn-<name>/`.

Add one: `just scenario-add <name> from <session> [frame]` (session = the `<ts>` of `logs/input-<ts>.txt` with its
`profile-<ts>/` bundle) writes a `start` scenario with an `exit` check and the session's marks in `source`; edit
`tests`, `frame` and checks, add refs, and make it `regression` only after two runs agree.
