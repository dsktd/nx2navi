# System changes made on this Steam Deck for NX2navi

Each entry: what, why, measured effect (build line), how to undo. Nothing here is applied unless marked APPLIED.

## Not system changes (files only, user deck)
- `~/nx2navi/` (game, data, scripts) and 348 Nix store paths added to `/nix/store` (2.8 GB, the game's libraries and
  Mesa 26.2.6; `/nix` already existed, owned by deck). Undo: `rm -rf ~/nx2navi`; the store paths are listed in
  `~/nx2navi/nix-closure.txt` (`chmod -R u+w` then `rm -rf` each).
- Steam: non-Steam entry "NX2navi" -> `~/nx2navi/play.sh`. Undo: remove it in Steam (Manage > Remove non-Steam game).

## APPLIED
- 2026-11-13 ~13:00, by Cal: udmabuf size limit 64 -> 4096 MiB, kept across reboots by /etc/tmpfiles.d/nx2navi.conf
  (`sudo ~/nx2navi/sys.sh udmabuf 4096`, `sudo ~/nx2navi/sys.sh persist`). Why: the game imports its memory as dma-bufs
  instead of keeping 5 GiB of shadow copies in RAM. Effect (entry=t1 vs t3/t4, exe=nx2navi.play50 commit=15d14ce, single
  runs): lowest MemAvailable in a field load 485 MiB -> 2.4-3.4 GiB. Undo: `sudo ~/nx2navi/sys.sh unpersist` and
  `sudo ~/nx2navi/sys.sh udmabuf 64` (or reboot after unpersist).

- 2026-11-13 ~13:14, by Cal, rebooted, /proc/cmdline has ttm.pages_limit=3145728: GPU memory limit 8 -> 12 GiB (`sudo ~/nx2navi/sys.sh gtt 12`): kernel parameter ttm.pages_limit=3145728
  added to GRUB_CMDLINE_LINUX_DEFAULT in /etc/default/grub (backup /etc/default/grub.nx2navi-bak) + update-grub. Why: the
  game needs about 9.5 GiB of GPU-visible memory after a save load (5.9 GiB of its own memory imported + 2.9 GiB textures
  and targets) and amdgpu allows 8 GiB GTT + 1 GiB VRAM: every scenario ends in "Not enough memory for command
  submission" / device lost at 9.2-9.5 GiB (entries t3 t4 t5 scan-*, play50 15d14ce). Undo: `sudo ~/nx2navi/sys.sh gtt stock`, reboot.
  Effect (entry=f4, play50 15d14ce): the field loads and runs (11.9 GiB GPU-visible at the peak) with texture detail low and
  8 MiB spans; with the larger limit the runtime's automatic texture detail goes to full and memory runs out again (f3),
  so play.sh sets texture detail low.

## Candidates (prepared, NOT applied)
- CPU EPP balance_performance -> performance (`sudo ~/nx2navi/sys.sh epp performance`). Undo: `... epp balance_performance` or reboot.
- GPU power level auto -> high (`sudo ~/nx2navi/sys.sh gpu high`). Undo: `... gpu auto` or reboot.

## Game settings on this Deck (build/v111/nx2navi.ini; the desktop's file was never copied)
Found 2026-11-13 (entry=deck-play50 exe=nx2navi.play50 commit=15d14ce): with no settings the game drew its own
2560x1440 picture with a 1920x1080 scene and shrank it to 1280x720 for the panel. The picture cannot be narrower than
16:9 (runtime/widescreen.c), so 16:10 is a 1280x720 picture with 40-line bars above and below (aspect = fit).
APPLIED 2026-11-13 13:40 in build/v111/nx2navi.ini and play.sh (not yet A/B'd one by one):
- game_res = 1080: the smallest picture the game has (1920x1080, scene 1440x810) instead of 1440.
- scene share (NX2NAVI_SCENE_SHARE in play.sh): scene as a share of the picture, 0.667 = 1280x720 = the panel.
- fps_limit = 60, fullscreen, window 1280x800, perf_overlay = fps.
Undo: delete the lines (or the file); the Steam Deck device profile of the runtime then gives its defaults.
- play.sh also sets NX2NAVI_DMABUF_MB=8 (smaller imported spans: 5.4-7.0 GiB instead of 7.2+) and NX2NAVI_TEXTURE_DETAIL=low.
- Deck access: login `tally` (wheel) runs the game and these files as `deck` through sudo.

## Offline building on the Deck (2026-11-13 14:20-14:35)
- By root (login tally): `/home/purplg/claude/nx2navi` created, owned by deck (5.0 GB): the build tree at the desktop's
  paths (sources `.lab/wt-deck` as a git checkout of branch deckres, build-linux.py, runtime-linux, kit venv, lifted
  code, deck2's objects, .ccache). 156 more Nix store paths (3.3 GB, the flake dev shell's toolchain) in `/nix/store`.
  `~/nx2navi/deckbuild.sh <name> [patch.mbox...]` builds there with `~/nx2navi/devenv.sh` (nix print-dev-env), no Nix
  install and no network. Undo: `sudo rm -rf /home/purplg`; store paths as above.
- Test 14:29-14:35 (`offline-test.sh`, root): deck3 = deck2 + a 1.2 KB patch built inside `unshare -n` in 243 s. For the
  game run an nft table `inet nx2cut` dropped everything but ssh and loopback for about a minute; it was deleted at the
  end (checked: gone). Steam went offline for that minute and logged on again at 14:34.

## Steam entry exe, deck4, offline tree for the new base (2026-11-13 15:10-15:40, deck agent 2)
- play.sh reads ~/nx2navi/play.env (kept): NX2NAVI_EXE=deck4 (d2d2e64 = upstream v0.10.1 5ae55db merged with the deck
  stack) and its own pipeline cache build/v111/pipeline-cache-deck4.bin. No play.env = deck2 (kept as play.env.deck4).
- show.sh / direct.sh: one foreground start through the entry / one pinned field run on DISPLAY=:1 without Steam.
- The entry stopped starting the game at 14:29 because Steam shows a "cloud sync failed" dialog for the controller
  configs (app 241100) since the offline test's network cut: press "Play anyway" or restart Steam.
- /home/purplg (the offline build tree) was gone at 15:01 (removed by someone else); recreated by root for the new
  base (2.3 GB, owned by deck), deckbuild.sh now builds .lab/wt-rebase6 into v111-rebase6. Undo: sudo rm -rf /home/purplg

