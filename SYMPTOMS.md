# NX2navi symptoms

One line per symptom Cal or the lab reported: first-seen build, status, the build where it changed, evidence. Lab agents add
a row when they see a new symptom and change `status`/`changed in` when a build moves it, quoting the build (exe, commit
from `builds.tsv`). Numbers for the performance symptoms are in `results.tsv`; the page `~/claude/.services/results/`
(proxy: /results/) charts both. Format is read by that page: keep the table columns and one symptom per row.
Status: `open`, `fixed`, `regressed`, `mitigated` (default off or lab-only fix, not played by Cal yet).
Seeded 2026-11-12 from the tracker, ARCHITECTURE.md, README and the board; first-seen builds before the provenance line
(play23) are the nearest named build and marked `~`.

| symptom | tracker | first seen | status | changed in | evidence |
|---|---|---|---|---|---|
| Scene-load freeze: Market-west 2.3 s, Graveyard 1.7 s held picture on the rebase | #132 | play32 (rebase; play13 was 0.4/1.0 s) | mitigated | play36 (0099 PRESYNC + 0101 POOL_IDLE_MS, knobs default off): 216/180 ms in lab cold loads | results.tsv `load cold west/grave`; ARCHITECTURE.md section 8; UNCERTAIN.md |
| Running stutter: >25 ms frames while riding/running in the field (44 fps, 520-750 frames/min over 25 ms) | #132 #173 | ~play11 (try-vram) | open | none; play32 at parity with play13 in the scripted run, which is itself noisy (174-624/min run to run) | results.tsv `field-pan`; ARCHITECTURE.md "Lab parity" |
| Rebase replay cost: shadow copy-in, write-back and table sync (~10 ms/frame) | #132 | play22 | mitigated | play24 WB_REARM, play29 NT, play31 TAB_DIRTY, play35 TOUCH_LOCK (-1.5 ms west) | results.tsv `ab_replay_BminusA_ms`; ARCHITECTURE.md section 8 |
| 240 fps target not reached; 51 fps at 60 target, worst frames 38-48 ms | #128 #132 | play2 ~ | open | none | tracker; results.tsv `fps` |
| Epona / streaming slowdown: pool_fini waits, 49 ms pipeline builds, 94k texture releases | #173 | play11 (try-vram) | open | none | tracker #173 |
| Live textures grow to 14 GB in long sessions, card over budget, 34 fps | #160 | play (just try) 2026-11-10 | mitigated | play13 (0052/0065/0075 trim, recycle, 0078); rebase still shows 4.6k to 14k live textures | tracker #160; BOARD baseline note |
| GPU-generated foliage missing (grass, hedge leaves): indirect mesh draws count 0 | #168 | play3 ~ (both translators) | fixed on the rebase, open on play13 | play22 (upstream device-address-table sync; field grass renders on play31/32, not play13) | ARCHITECTURE.md "Lab parity"; tracker #168 |
| Flickering ambient occlusion / lighting flicker with camera or time of day | #146 #175 | play ~ (2026-11-09) | mitigated | play13 AO_ORDER=1 (0016); play26 EVO_ASYNC=1 fixes play24 flicker; #175 distant shadows still open | README 0013/0016/0090; tracker |
| Red / rainbow cliffs, Jabu-Jabu scene posterised blue haze | #164 | nx2navi.vram (0052) | fixed | 0054/0065 (trim converges, SHADOW_REWRITE) before play13 | tracker #164, .lab/issue-jabu-blue |
| Terrain tile stretched into a column / terrain chunks missing then pop in | #169 #149 | play8 ~ | mitigated | 0074 stale rule (play13); #169 not re-checked on rebase | tracker #169 #149 |
| Market / Graveyard lag after entry (held pictures, 4,869 texture makes under frame_hold) | #132 | play32 | mitigated | play34 POOL_LOAD_FIT/STEP (lab: 16 fr/1945 ms down to 4/1298); play36 | BOARD 2026-11-12 play34 line |
| Black/gray bushes, Link and plants black at sunset | #138 #150 | play ~ | open | none | tracker |
| Pale fog strip, stray rod of geometry, red/black name plate, ocarina bar glyph, Goron flicker | #157 #158 #163 #155 #156 | play13 ~ | open | none | tracker |
| Ice cavern reflection upright/offset | #174 | play21 (tld) | open | none; NX2NAVI_TLD_CLAMP (0081) tried, halo hunt continues | tracker #174 |
| Occasional GPU device loss | #141 | play ~ | open | none | tracker #141 |
| Boot abort (SDK Break svc 0x26) in builds made while another build ran | - | play33 | fixed (process) | rebuilt under `flock /tmp/nx2navi-build.lock` | BOARD 2026-11-12 |
| Measuring beside a build gives 30-40 ms frames | - | lab | fixed (process) | tools/ab-cell and load-cell wait for loadavg under 6 | BOARD 2026-11-12 |
