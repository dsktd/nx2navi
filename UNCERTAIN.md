# Uncertain settings

Things that are on or available without proof they help. One line each; remove a line when it is settled.

| Setting | Default | Status | Turn off / on |
|---|---|---|---|
| CPU pinning to one cache domain | on (`just play`) | lab 2026-11-10: same mean (42.6/43.0 unpinned, 42.2/42.7 pinned), steadier tail (p99 29.0/28.7 to 27.8/27.3 ms); Cal: feels faster and steadier. Keep. | `NX2NAVI_CPUS=off` |
| `NX2NAVI_GPU_WAIT` | 0 | off fixed the horizon bands by observation, not re-proven | `=1` |
| `NX2NAVI_AO_ORDER` | 0 | lab: `=1` makes the shading read this frame's depth in 300 of 300 frames with no brightness outliers and no fps cost (old `EVENT_WAITS` had 5 dark frames and a darker picture); final picture under motion not compared; needs Cal's eyes | `=1` |
| `NX2NAVI_AO` | on | `=0` turns the ambient shading off: creases lose their soft darkening, graveyard 2-3% brighter; fallback if the fix is not enough | `=0` |
| `NX2NAVI_EVENT_WAITS` | off | fixes AO flicker, causes fullscreen flicker and a soft picture | `=1` |
| `NX2NAVI_AO_ORDER` | 0 | AO reads this frame's depth; lab clean at two spots; real play untested | `=1` |
| `NX2NAVI_AO` | 1 | `=0` is the steady fallback without ambient occlusion | `=0` |
| `NX2NAVI_ONESHOT_WAIT_MS` | 30000 | a low cap would cut combat hitches; picture untested | `=<ms>` |
| `NX2NAVI_TEX_RELEASED_MIB` | 3072 | graveyard may want more; higher risks video memory | `=<MiB>` |
| `NX2NAVI_TEX_RELEASED_YIELD` | off | lab at Death Mountain with `=60`: video memory 11.5 to 9.7 GiB, fps 53.6 to 55.0, worst upload 775 to 428 ms; `=85` proposed for play but never fires in the lab (area sits at 69%); in `nx2navi.vram`; needs Cal's full-card session | `=85` |
| `NX2NAVI_ALIAS_EXTRA_MIB` | 0 | lab: `=512` removes all refused memory maps (71 to 0 over 16000 frames; the game wants about 200 MiB more than its budget); not shown to remove the vanishing ground; in `nx2navi.crash` only; needs Cal's play test | `=512` |
| `NX2NAVI_OQ_FORCE` | 0 | Cal plays with `=1` since 2026-11-10: Goron City holes gone, but it was his second visit (first-visit effect not ruled out) | `=1` |
| CPU pinning lives in `just play` only | - | the Flatpak launcher does not pin; move into the runtime if pinning proves itself | - |
| `NX2NAVI_MOTION_PAD` | auto | no effect while yakin holds the controller | `=off` |
| `NX2NAVI_SHADOW_NT` | off | lab field window: shadow sync 2.9 -> 2.0 ms/frame, 42.4 -> 43.6 fps, p99 -1 ms (two runs); with Cal's set (YIELD, ALIAS, AO_ORDER) in `nx2navi.next`: 42.8/42.0 -> 43.4 fps, replay 19.9/20.3 -> 19.4 ms, castle and crash shots match; two NT runs and one run without NT had host-side slow patches (void); needs a play session | `=1` |
| `NX2NAVI_SHADOW_GAP_KIB` | 64 | `=2048`: write-watch queries 232 -> 160 a frame, sync -0.05 ms only; harmless, little gain | `=2048` |
| `NX2NAVI_POOL_KH` | 0 | lab field: replay -0.4 ms, +0.8 fps (3 on, 2 valid off runs, inside the spread); shots match; in `nx2navi.bind` | `=1` |
| `NX2NAVI_MOTION_SOCK` | auto | yakin socket motion: fake-server probe only; real controller and in-game axis signs untested; in `nx2navi.motion` | `=off` |
| `NX2NAVI_TEX_RT_TRIM` + `NX2NAVI_TEX_RT_DEDICATED_MIB` | 95 / 4 | #160: released render targets get own memory and go above 95% of the driver budget; built only, no GPU run yet (black-flash risk of dropping a render target as under the yield); in `nx2navi.vram` | `=0` / `=0` |
| surface pick (`pick.req`, F5) | on in `just try` (on request) | #165: built only; never run on the GPU; the doubled draw at the centre pixel and query pool are unverified | do not pick |
| `buf.req`, re-armable `watch.req`, `dump.req` options | on in `just try` (on request) | built only, no live run yet | do not write the files |
| `NX2NAVI_TEX_STALE_GONE` | 0 | #160: stale bindless slots of destroyed finalized textures resolve to nothing instead of a new live entry; risk: a game draw that samples a finalized texture's slot gets a stand-in (missing texture) | `=0` |
- NX2NAVI_TEX_LIVE_EVICT=85 (0072, play8): drops idle live mirrored textures under VRAM pressure; default on, unverified in game; 0 restores old behaviour.
| `NX2NAVI_TEX_SAME` (upstream 42ae87b) | 1 | skips re-uploads of small textures whose bytes match; lab A/B pending (.lab/p20) | `=0` |
