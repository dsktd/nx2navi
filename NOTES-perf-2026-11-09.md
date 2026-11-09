# #132 performance: Cal's real-play Tracy trace (2026-11-09)

Trace `~/claude/ya.trace.tracy` (Tracy 0.13.1, `build/v111/nx2navi.tracy` = patch 0023 on the host, `just play`
defaults: 240 fps limit, HDR native, `PIPE_SKIP=any`, `REPLAY_ASYNC=1`, `VK_RECORDER=1`, `TEX_RELEASED_MIB=3072`;
play log `play-20261109-164936.log`). 80 s of play: Hyrule Castle at 100-160 fps, a load into Hyrule Field at 27.8 s,
then the field, the last 30 s at a flat 43 fps. CPU zones only (no GPU zones yet), frames marked at `perf_present`.

## Method

`tracy-csvexport` (nixpkgs tracy) gives whole-trace zone statistics, `-u` every zone event with its start time, thread
and value, `-u -p` the plots. It does not export the frame marks, so a scratch copy of `csvexport/src/csvexport.cpp`
got 12 lines that print `worker.GetFrames()` (set, index, begin, end, duration; Tracy's own `Worker`, built with
`nix develop nixpkgs#tracy`, env `CSV_FRAMES=1`). Zone events were bucketed into the frame whose
[begin, end) holds their start, so a zone on another thread counts in the frame it ran during, not the frame it
belongs to logically. Frames 0 and 1 (before the profiler connected, and the 8.7 s ring gap) are left out.

Threads in the export: t1 = the game's render thread (`nvn submit` 2/frame, `submit finish wait`, the frame mark),
t2 = `vk replay` (shadow sync, bind pipeline, texture upload, released sweep), t3 = audio, t4 = one `shadow sync` per
frame (1 us), t5 = `vk completion` (write-back compare, write-back), t6 = a second guest thread submitting 4/frame.

## Timeline, 5 s buckets (means per frame, ms)

| t (s) | frames | frame ms | fps | finish wait t1 | wb compare t5 | shadow sync t2 | audio t3 | upload ms | upload MiB (sum) | binds/frame |
|---|---|---|---|---|---|---|---|---|---|---|
| 9 | 533 | 9.4 | 106 | 0.2 | 0.0 | 0.3 | 0.2 | 0.0 | 26 | 6 |
| 14 | 807 | 6.2 | 162 | 0.3 | 0.0 | 0.2 | 0.2 | 0.0 | 2 | 24 |
| 19 | 639 | 7.8 | 128 | 0.1 | 0.0 | 0.0 | 0.1 | 0.0 | 0 | 3 |
| 24 | 532 | 9.8 | 102 | 2.6 | 0.0 | 0.2 | 0.1 | 1.3 | 1806 | 5 |
| 29 | 130 | 36.9 | 27 | 6.4 | 7.5 | 3.7 | 2.3 | 2.8 | 721 | 613 |
| 34 | 166 | 30.0 | 33 | 7.9 | 7.6 | 3.2 | 1.9 | 0.3 | 37 | 624 |
| 39 | 166 | 30.1 | 33 | 8.3 | 7.5 | 2.9 | 1.9 | 0.1 | 2 | 613 |
| 44 | 165 | 30.3 | 33 | 7.7 | 7.8 | 3.0 | 2.0 | 0.1 | 1 | 611 |
| 49 | 190 | 26.3 | 38 | 6.4 | 6.5 | 2.7 | 1.6 | 0.1 | 1 | 612 |
| 54 | 222 | 22.5 | 44 | 5.1 | 5.3 | 2.7 | 1.3 | 0.1 | 1 | 612 |
| 59-84 | 1172 | 22.4-23.4 | 43-45 | 4.8-5.3 | 5.2-5.7 | 2.7 | 1.4 | 0.1 | 0-1 | 606-613 |

The castle part (9-27 s) has 3-24 pipeline binds per frame and no write-backs; the field has ~610 binds and 162
written ranges per frame. The field is slow in steady state, not because of spikes.

## 1. Frame-time distribution

| window | frames | mean ms | p50 | p90 | p99 | max | mean fps |
|---|---|---|---|---|---|---|---|
| whole trace | 4722 | 16.28 | 14.85 | 29.50 | 41.73 | 741.04 | 61.4 |
| before the last 30 s | 3412 | 13.75 | 7.75 | 30.88 | 45.03 | 741.04 | 72.8 |
| last 30 s (field) | 1310 | 22.90 | 22.97 | 25.08 | 27.36 | 31.62 | 43.7 |

Frames over the 4.17 ms budget: 4305 of 4722 (last 30 s: all 1310; none over 33 ms there). The 1% low of the play
log's own 60 s window agrees (66.5 fps mean, 1% low 22.9 fps).

Worst 10 frames of the whole trace (ms, zoned time inside the frame):

| t (s) | frame | finish wait t1 | shadow sync t2 | texture upload t2 | upload MiB | wb compare t5 | audio t3 | note |
|---|---|---|---|---|---|---|---|---|
| 27.79 | 741.0 | 710.3 | 107.6 | 321.2 | 792 | 6.9 | 10.6 | field load: 3 syncs of 37/30/31 ms (71/226/52 fresh pools), uploads of 40-59 MiB each |
| 28.53 | 340.3 | 305.0 | 3.4 | 171.2 | 433 | 5.8 | 4.2 | load, second batch |
| 28.87 | 315.9 | 271.3 | 3.5 | 207.0 | 580 | 5.6 | 3.6 | load, third batch |
| 19.01 | 250.8 | 0.2 | 0.0 | 0.0 | 0 | 0.0 | 4.0 | castle: nothing zoned (a pool_fini wait: the log counts 47 of them, 793 ms, in frames 1800-3600) |
| 19.55 | 112.3 | 0.2 | 0.0 | 0.0 | 0 | 0.0 | 1.8 | same |
| 10.36 | 69.4 | 0.2 | 0.0 | 0.0 | 0 | 0.0 | 0.8 | same |
| 29.53 | 67.0 | 30.0 | 15.1 | 0.1 | 0 | 5.7 | 4.2 | post-load settling |
| 19.73 | 66.7 | 0.2 | 0.0 | 0.0 | 0 | 0.0 | 1.2 | castle, unzoned |
| 32.60 | 63.5 | 19.1 | 4.1 | 8.7 | 16 | 13.1 | 4.3 | field, re-upload storm |
| 30.63 | 58.2 | 21.1 | 5.9 | 8.1 | 11 | 8.8 | 3.6 | field, re-upload storm |

The shadow sync maximum of the summary (37.2 ms) is the first sync after the load at 27.81 s (71 fresh pools), inside
the 741 ms frame, together with 792 MiB of uploads: load, not play. 30.2-31.2 s is the post-load re-upload storm
(10-16 MiB and 6-7 ms of re-uploads per frame, 10-13 ms of write-back compare, 5-7 ms of shadow sync, 50 ms frames);
it is over after a second. No shadow sync over 5 ms after 31.2 s.

Worst 10 frames of the last 30 s (ms): all 27.6-31.6 ms, all of the same shape: finish wait 5-10, wb compare 5.5-7.4,
shadow sync 2.5-3.9, audio 1.6-2.3, uploads 0.1-0.2, 646 binds. Nothing spikes; the field frame is simply long.

## 2. Zone budget per frame, last 30 s (1310 frames, mean frame 22.90 ms)

| zone | thread | ms/frame | of 4.17 ms | calls/frame | max in a frame |
|---|---|---|---|---|---|
| submit finish wait | t1 game | 5.07 | 122% | 1.0 | 10.3 |
| write-back compare | t5 completion | 5.42 | 130% | 162 (66 MiB compared) | 10.3 |
| shadow sync | t2 replay | 2.71 | 65% | 11.1 (771 pools touched) | 4.8 |
| audio mix | t3 audio | 1.39 | 33% | 4.6 | 2.5 |
| write-back | t5 completion | 0.36 | 9% | 162 | 0.8 |
| nvn submit | t6 guest | 0.13 | 3% | 4.0 | 0.5 |
| bind pipeline | t2 replay | 0.085 | 2% | 609 | 0.2 |
| texture upload (all re-uploads) | t2 replay | 0.064 | 2% | 2.4 | 0.2 |
| nvn submit | t1 game | 0.005 | 0% | 2.0 | 0.2 |
| released sweep | t2 replay | 0.001 | 0% | 38 | 0.0 |

Correlation of frame time with per-frame zone sums over the last 30 s: binds 0.67, finish wait 0.63, bind pipeline
0.59, shadow sync 0.53, write-back compare 0.53, audio 0.46, write-back bytes 0.05. Draw count drives everything.

Whole-trace means for comparison: finish wait 3.15, write-back compare 2.87, shadow sync 1.44, audio 0.82, texture
upload 0.27 (+0.07 re-uploads), write-back 0.20 ms per frame.

Texture uploads over the whole trace: 15289 uploads, 1.29 s in total, of which 8574 re-uploads; 1.8 GiB in the load
bucket at 24-29 s, then 721 MiB in 29-34 s, then 0-37 MiB per 5 s. With the 3072 MiB cap the re-upload storm of
NOTES "VRAM pressure" is gone in steady state: 2.4 re-uploads and 0.06 ms per frame in the last 30 s.

## 3. What the zones do not cover

| thread | zoned ms/frame (last 30 s) | unzoned | what runs there |
|---|---|---|---|
| t1 game | 5.08 | 17.8 (78%) | guest code and the NVN API on the render thread: command recording, texture/pool init and fini (the blocking ones: `pool_fini`, `finish`, `write_texels`), `nvnQueuePresentTexture`, the pacer |
| t2 replay | 2.93 | 20.0 (87%) | the replay itself: `vk_exec` draw recording, descriptor and pipeline lookups, `vkQueueSubmit2` per part, `present_image`, the mirror prologue, `vk_texture_new_submit` |
| t5 completion | 5.78 | 17.1 | `vkWaitSemaphores`, timestamp reads, descriptor pool resets, `vk_mem_collect` |
| t3 audio | 1.39 | - | its own thread |
| t6 guest | 0.13 | 22.8 | the producer thread (also home of the LOD guard wait, unzoned) |

Which thread is the critical path: the play log's `vk: replay queue at frame 3600: ... frame bound 1800 calls, 0 waited`
(the game thread never waited for the replay thread at a present, over the whole run) and `pool_fini 150 calls,
47 waited 792.7 ms` say the replay thread keeps up and the **game's render thread (t1) is the bottleneck**: 5.1 ms of
it is the finish wait, 17.8 ms unmeasured. Unzoned t2 time is not a frame cost until t1 gets faster.

The finish wait is longer than it looks. `vk_sync.c completion_main` publishes `done` only after it ran every
callback up to the reached value (`cb_done` -> `vk_gpu_written` -> write-back compare and write-back, then
`vk_mem_collect`), and `fence_wait_impl` waits on `done`. So the game thread's `submit finish wait` for the first
submission of a frame includes (a) the GPU draining everything queued before it, (b) the first submission's own GPU
time, and (c) the completion thread's callbacks, i.e. the 5.4 ms/frame of write-back compares that are due by then.
The LOD guard (`nvn_api_core.c obs_release_read`, on by default) waits on the same `done` from the producer thread.

## 4. Fixes, ranked

1. **Take the write-back compare off the finish wait** (`vk_sync.c`). Give the completion thread a second counter,
   `reached_gpu`, stored (release) right after `vkGetSemaphoreCounterValue` and before the callback loop, and a
   `vk_sync_gpu_wait(value)` that waits on it (same `cv_done`, broadcast once more after the store). Use it for
   the `submit finish wait` in `nvnQueueSubmitCommands` and for the LOD guard: both exist to order the GPU's reads of
   guest memory before the game rewrites it, which the GPU's completion already guarantees; the write-backs of that
   submission land through the normal path, as for every other submission. `fence_wait` (nvnSyncWait, finish) keeps
   waiting on `done`. Expected: up to 5 ms off the game thread's 22.9 ms frame (43 -> ~55 fps), realistically
   2-4 ms. Measure the upper bound first at no cost: `NX2NAVI_SUBMIT_FINISH=0 just play` for a minute in the field
   (known risk: white dialogue frames; the field has few).
2. **Parallel write-back compare** (`vk_memory.c shadow_diff`, patch 0008 area). 162 ranges and 66 MiB per frame
   compared page by page on one thread: 5.4 ms = 12 GB/s, memory-bound. Split the ranges over 3-4 workers (a small
   pool woken by `cb_done`, or `shadow_diff` over page stripes with the runs merged in order) and the compare drops to
   ~1.5-2 ms; it also shortens `done` for the real fence waits and the LOD guard. Keep the run list per worker and
   concatenate, `shadow_write_back` stays under `shadow_lock` as today. Expected: 3-4 ms off the completion thread
   per frame, visible as frame time only through the waits of item 1 (so do 1 first, or measure both).
3. **Shrink the written ranges** instead of comparing them: the ranges are what the replay bound as writable (storage
   buffers reached through pointers bind to the end of their backing, 4-15 MiB each, of which the compute passes
   change a few KiB, per the 0001 comment). A per-pipeline table of the largest offset a storage write can reach
   (from the translator's reflection, or learned: record the max page the compare found changed per (pipeline,
   binding) and clamp the written range to that plus a margin) cuts both compare and write-back bytes by an order of
   magnitude. More work and a correctness argument; after 1 and 2.
4. **Shadow sync** (2.7 ms/frame on the replay thread, 11 parts, 771 touched pools; not on the critical path today).
   The per-part cost is dominated by the pool count, not the call count. Options: skip the write-watch query for pools
   whose region stamp (`reg_max`) is older than the last sync (already done per region, so measure the 2 MiB-region
   page scan next with a zone on `shadow_sync_pool`), and batch the 11 syncs per frame into fewer when consecutive
   parts have no CPU writes in between. Expected 1-1.5 ms on t2, matters once t1 is fixed.
5. **Load hitch** at area entry (741 + 340 + 316 ms frames, 1.8 GiB of uploads in 0.6 s, three 30-37 ms shadow syncs
   of fresh pools). Not a play-rate issue; if wanted, the uploads could be issued from a second staging ring while the
   game thread is released after the first sync, and the fresh-pool shadow copies could use `memcpy` of whole pools
   without the page scan (`shadow_sync_pool`, tracked == 0 path). Expected: the 1.4 s stall halves.
6. **Audio** 1.4 ms/frame on its own thread (0.3 ms per 5 ms mix): fine.
7. **Pipeline binds**: 609 per frame, 0.085 ms: fine. The bind count is the best cheap proxy for draw load.

Not a fix but the next measurement: the 17.8 ms of unzoned game-thread time per frame. Tracy's sampling view
(host: `sysctl kernel.perf_event_paranoid=1` for the run, then the GUI's Statistics -> Sampling, thread `t1`) or
`perf record -t <render tid>` on the host splits it into guest code vs. NVN API vs. blocking; the zones below cover
the blocking part.

## 5. Zones to add (patch 0023 follow-up)

- `frame bound` / `replay full` around the two `plat_cond_wait` loops in `vk_backend.c` (`vk_be_present`,
  `replay_enqueue`), and `replay drain` in `replay_drain` with the `why` as value: the game-vs-replay question answered
  per frame, not per 1800.
- `nvn block <name>` in the blocking NVN entries (`pool_fini`, `finish`, `write_texels`, `nvnSyncWait`,
  `nvnWindowAcquireTexture`, `nvnQueuePresentTexture` incl. the pacer): one zone each where `NVN_BLOCKING()` is, so the
  game thread's waits are visible without zoning every NVN call.
- `replay submit` around `submit_sync` in `replay_main` (value `n`) and `part submit` around `vkQueueSubmit2` in
  `vk_sync_split` (value `cur_fence`): the replay thread's per-frame recording cost and part count.
- `completion cb` around `p.fn(p.arg)` in `completion_main` (value: the fence) and `lod guard` around the wait in
  `obs_release_read`: shows how much of the finish wait is callbacks (item 1 above) and whether the producer thread
  stalls.
- Later, GPU zones: a C shim over `TracyCGpu*` (the C API has `___tracy_emit_gpu_*`) fed from the existing timestamp
  pairs in `vk_sync.c ts_*`, so the GPU's share of the 22.9 ms is known.

## Kakariko 2026-11-09 (before)

Trace `~/claude/kak.tracy` (Tracy 0.13.1, 59 MB, same binary and env as the field trace: `build/v111/nx2navi.tracy`,
240 Hz, HDR native, `PIPE_SKIP=any`, `REPLAY_ASYNC=1`, `VK_RECORDER=1`, `TEX_RELEASED_MIB=3072`). 86 s: menu and
loading until 30 s, then Kakariko Village to the end, Cal **running around the whole time** (the field trace was
standing still, no inputs). Same method and scratch `csvexport` as above (`perf-scripts/an3.py`, `an4.py` in the
scratchpad: thread ids differ per trace, so roles are detected: t3 = game render thread, t2 = replay, t6 = completion,
t1 = audio, t4 = second guest thread, t5 = the 1 us shadow sync). `build/` was not mounted in the container when this
was written, so the play log's counters (`pool_fini`, `frame bound`, pipeline compiles) are not quoted.

**Window.** The last load spike is the 505 ms frame at 27.07 s followed by 106-217 ms frames until 28.6 s; the
post-load re-upload storm (52-62 ms frames, 15-21 MiB of re-uploads each) ends at 30.7 s. Cal's boundary of 30 s
matches: everything from 30.0 s to the end (1991 frames, 55.9 s) is the Kakariko window below; 30.0-30.7 s adds
three storm frames to it, which does not move the means.

### 1. Frame-time distribution

| window | frames | mean ms | p50 | p90 | p99 | max | mean fps | >16.7 ms | >33 ms |
|---|---|---|---|---|---|---|---|---|---|
| whole trace | 3131 | 24.64 | 22.92 | 35.76 | 51.32 | 504.92 | 40.6 | 2553 | 458 |
| before 30 s (menu + load) | 1140 | 18.65 | 16.70 | 18.94 | 70.61 | 504.92 | 53.6 | 571 | 51 |
| Kakariko 30 s-end | 1991 | 28.07 | 27.16 | 37.06 | 50.47 | 65.54 | 35.6 | 1982 | 407 |
| last 30 s | 1007 | 29.77 | 29.08 | 38.33 | 51.47 | 65.54 | 33.6 | 1006 | 301 |

Every Kakariko frame is over 4.17 ms and all but 9 over 16.7 ms; 20% are over 33 ms. The menu runs at a flat 16.70 ms
(the game's own 60 Hz pacing) with three unzoned 80-109 ms stalls (10.6, 21.3, 21.5 s: nothing zoned in them, the
`pool_fini`-wait shape of the castle part above).

### 2. Zone budget per frame, Kakariko window (1991 frames, mean frame 28.07 ms)

| zone | thread | ms/frame | of 4.17 ms | of 16.7 ms | calls/frame | per frame | max in a frame |
|---|---|---|---|---|---|---|---|
| submit finish wait | t3 game | 5.35 | 128% | 32% | 1.0 | | 27.3 |
| write-back compare | t6 completion | 5.09 | 122% | 31% | 157.5 | 61 MiB compared | 12.9 |
| audio mix | t1 audio | 2.93 | 70% | 18% | 5.6 | 0.52 ms per call | 10.2 |
| shadow sync | t2 replay | 2.81 | 67% | 17% | 11.9 | 747 pools touched | 8.7 |
| texture upload (first-time) | t2 replay | 0.77 | 18% | 5% | 10.7 | 1.92 MiB | 13.3 |
| write-back | t6 completion | 0.52 | 13% | 3% | 157.1 | | 2.1 |
| texture upload (re-uploads) | t2 replay | 0.29 | 7% | 2% | 7.5 | 0.35 MiB | 5.3 |
| nvn submit | t4 guest | 0.17 | 4% | 1% | 4.0 | | 0.9 |
| bind pipeline | t2 replay | 0.09 | 2% | 1% | 645 | | 0.2 |
| released sweep | t2 replay | 0.01 | 0% | 0% | 39 | | 0.3 |
| nvn submit | t3 game | 0.01 | 0% | 0% | 2.0 | | 0.1 |

### 3. Steady-state vs movement-triggered

Frames split by whether the replay thread uploaded more than 1 MiB of textures during them (means, ms per frame):

| set | frames | frame ms | finish wait | wb compare | wb ranges / MiB | shadow sync | pools | audio | upload ms | up MiB (first / re) | binds |
|---|---|---|---|---|---|---|---|---|---|---|---|
| quiet (no uploads) | 1612 (81%) | 26.3 | 5.11 | 4.98 | 156 / 61 | 2.77 | 744 | 2.77 | 0.14 | 0.02 / 0.02 | 643 |
| movement (uploads) | 379 (19%) | 35.6 | 6.41 | 5.58 | 162 / 61 | 2.99 | 755 | 3.57 | 3.46 | 10.0 / 1.8 | 654 |
| Hyrule Field, last 30 s (above) | 1310 | 22.9 | 5.07 | 5.42 | 162 / 66 | 2.71 | 771 | 1.39 | 0.06 | 0 / 0.1 | 609 |

- **Per frame regardless of movement:** write-back compare (156-162 ranges, 61 MiB, 5.0-5.6 ms), shadow sync
  (11.9 parts, 745-755 pools, 2.8-3.0 ms), finish wait (5.1 ms baseline), binds (~645). They are the same numbers as
  the field within 10%; the compare and sync counts do not scale with movement, they are a fixed per-frame tax of
  the written-range and pool bookkeeping.
- **Movement-triggered:** texture uploads. 19% of the frames carry them and are 9.3 ms longer: 3.5 ms of upload on
  the replay thread (10 MiB first-time + 1.8 MiB re-uploads per such frame), +1.3 ms finish wait, the rest unzoned.
  Over the window: 3.75 GiB uploaded first-time and 0.69 GiB re-uploaded, 100-300 MiB/s during 68-86 s while running
  through the village; 26298 uploads, of which 15520 re-uploads, but the re-uploads are mostly tiny (5838 of 3 KiB,
  4060 of 128 B, 3818 of 512 B: palettes and small dynamic textures); the bytes are first-time 2 MiB
  (2078720 B x 1026) and 0.4-0.5 MiB textures. With a 3072 MiB cap nothing should be evicted, so either Kakariko's
  running route really touches 3.7 GiB of distinct textures (unlikely for OoT) or the cache key misses when the game
  re-creates texture objects over reused pool memory. Next zone value: cache hit / miss / released-hit per upload.
- **Audio** is 2.8-3.6 ms/frame here against 1.4 in the field: 0.52 ms per 5 ms mix (0.30 in the field), more
  voices in the village. Its 0.71 correlation with frame time is mostly cadence (a longer frame holds more mixes); it
  stays on its own thread. 23 mixes over 2 ms (max 7.2) all sit inside the stall block at 59.7-61.1 s.
- **Quiet frames are still 3.4 ms slower than the field** (26.3 vs 22.9) with identical zone costs, so the
  difference is unzoned game-thread time: 21.0 ms vs 17.8 (more actors: villagers, cuccos, the running Link).
  Quiet frames by quartile (20.0 / 24.1 / 27.9 / 33.3 ms) grow with finish wait (2.2 -> 7.4), binds (539 -> 722) and
  touched pools (603 -> 841): draw load is the driver inside the steady state, as in the field.

### 4. What the zones do not cover (window)

| thread | zoned ms/frame | unzoned | note |
|---|---|---|---|
| t3 game | 5.36 | 22.7 (81%) | 21.0 on quiet frames; field 17.8 |
| t2 replay | 3.97 | 24.1 (86%) | recording, pipeline creation (`PIPE_SKIP=any`: new village pipelines compile here, unzoned) |
| t6 completion | 5.62 | 22.4 | |
| t1 audio | 2.93 | 25.1 | own thread |

**Stall block 59.7-61.1 s**: ~20 frames of 50-65 ms, the worst of the window, with finish wait under 1.2 ms, uploads
3-20 MiB, normal compare and sync, and audio mixes of 7-10 ms per frame. Nothing zoned explains them and every thread
slows at once: a CPU-wide contention (pipeline compilation threads, or a page-fault burst on fresh pools) rather than
GPU or replay backlog. 36 of the 112 frames over 40 ms have this shape (also 32-33, 44-45, 69 s); the other 76 are
finish-wait frames (10-27 ms waits, movement frames with 20 MiB of uploads in front of the GPU work).

### 5. Load spike (Kakariko entry)

| t (s) | frame ms | finish wait | shadow sync | uploads | note |
|---|---|---|---|---|---|
| 27.07 | 504.9 | 476.9 | 85.0 (3 syncs: 14.7/68 pools, 23.1/190, 40.2/68) | 214 ms, 403 MiB (two 56 MiB uploads of 20 and 40 ms) | load |
| 27.57 | 105.7 | 89.2 | 2.5 | 45 ms, 140 MiB | |
| 27.68 | 216.9 | 160.6 | 3.3 | 123 ms, 290 MiB | |
| 27.90 | 132.8 | 41.5 | 3.3 | 61 ms, 157 MiB | |
| 28.03 | 184.2 | 39.6 | 3.1 | 116 ms, 324 MiB (16 and 12 MiB singles of 9-10 ms) | |
| 28.45-28.93 | 87, 86, 69, 53, 43 | 41, 44, 31, 22, 12 | 7-8 (1012-1260 pools) | 14-43 MiB each | first village frames, re-uploads start |
| 30.4-30.7 | 52-62 | 1-27 | 5-9 | 15-21 MiB re-uploads | storm, over at 30.7 s |

1.5 s of wall time for 1.4 s of stall; 2.4 GiB uploaded in 24-30 s. Same shape as the field entry (741 + 340 + 316 ms
there): shadow syncs of fresh pools and 50-60 MiB uploads inside the finish wait. Fix 5 above applies unchanged.

### 6. Verdict on fixes 1 + 2, and the Kakariko list

The steady-state bottleneck is the same: game thread waits 5.1-6.4 ms per frame on a `done` that includes 5.0-5.6 ms of
write-back compare, with the compare and sync volumes fixed per frame. Fixes 1 (GPU-only wait) and 2 (parallel compare)
apply as written and should take the same 3-5 ms off: 26.3 -> ~22 ms on quiet frames (38 -> ~45 fps), 35.6 -> ~31 on
movement frames. They do **not** cover the two things Kakariko adds: 9 ms per movement frame of texture uploads (19% of
frames) and the 3.4 ms of extra unzoned game-thread time, nor the 60 s stall block.

1. Fixes 1 + 2 as above (same code, same expectation).
2. **Texture upload path, movement frames.** First: a `texture upload` value of hit/miss/re-created to learn whether
   3.7 GiB in 56 s are distinct textures or cache misses on re-created objects over reused pools (`vk_texture.c`
   keying). If misses: key by (pool, offset, size, format, content hash of the first page) and reuse the existing
   image. Either way the upload itself (3.5 ms on t2 per movement frame plus the +1.3 ms finish wait) should go
   through a second staging ring submitted on the transfer queue, so the replay's draw recording is not behind the
   copies. Expected: movement frames from 35.6 to ~28 ms.
3. **Zone the stall block.** `vkCreateGraphicsPipelines` / `vkCreateComputePipelines` in the replay (with
   `PIPE_SKIP=any` the compile is the unzoned t2 cost on new village pipelines) and the write-watch page scan
   (`shadow_sync_pool`), so the 50-65 ms frames at 60 s are attributed. The play log of this run (host
   `build/v111/logs/play-20261109-17*.log`) has the pipeline counters; read it when `build/` is mounted.
4. **Unzoned game thread, 21 ms.** Same next measurement as the field (sampling), now more important: it is 3.4 ms more
   than the field at the same zone costs, and it is the frame floor once 1 + 2 land.
5. Shadow sync (2.8 ms, 747 pools, t2) and audio (0.52 ms per mix): unchanged ranking, not on the critical path.

## Kakariko texture uploads: classification (patch 0027, 2026-11-09 evening)

`NX2NAVI_TRACE=tex` (patch 0027, built into `nx2navi.new2`, not swapped) logs every 600 frames what the uploads are:
first-time uploads by the key's past (never seen / destroyed by range gone, replaced at address, released-count or
released-bytes sweep, VRAM pressure), repeats of bytes uploaded before (content hash; same key / other key), re-uploads
(of them after a take-back), take-backs, destroys by cause and the released list. The Tracy `texture upload` zone text
carries the same class. The cache key (`TexKey`) is address + the whole `nvn_texdesc` (format, size, target, levels,
swizzle, flags) + the 8-byte layout; a released entry at an address is destroyed when a *different* descriptor is
created there (`entry_of`), and `vk_texture_range_gone` (pool_fini) destroys every entry in the pool.

Lab replay of `input-20261109-165243.txt` (live profile, no bundle) to present 4200 with `nx2navi.new2`:

| frames | first-time | of them: new key / after sweep / pressure | same bytes seen before (same key / other key) | re-uploads | destroys: replaced / released-bytes sweep | released kept |
|---|---|---|---|---|---|---|
| 600-1200 (load) | 5688, 2058 MiB, 783 ms | 5677 (2048 MiB) / 0 / 0 | 5 (9.5 MiB) / 172 (12 MiB) | 3288, 318 MiB | 147 (412 MiB) / 15 (19 MiB) | 920 (3021 MiB) |
| 1200-4200 | 21, 10 MiB | 0 / 10 (4.9 MiB) / 11 (5.3 MiB) | 20 (9.9 MiB) / 0 | 2100-3100 per 600 frames, 2-4 MiB, 35-48 ms | 160-580 (0.9-4.4 GiB) / 1058-2446 (4.2-10.5 GiB) | 660-740 (3.0 GiB) |

- The 2 GiB scene load is genuine: unique content under new keys (content-hash repeats 1%). Nothing is uploaded again
  because of the key or the released list after it: zero "after range gone / replaced" first-time uploads.
- The replay did not reproduce Cal's 3.75 GiB of first-time uploads over 56 s of running (it starts from the live
  profile's save, not the recording's; frames 1200-4200 are steady state with 0 first-time uploads). The field's
  Tracy shape (10 MiB first-time per movement frame, 2 MiB x 1026) therefore most likely comes from **scene/area
  loads along his route** (houses, well, graveyard: each a fresh pool with unique content), not from key misses.
  To confirm: `NX2NAVI_TRACE=tex just play` for a minute of running around Kakariko and read the `tex:` lines.
- The re-uploads are what the field had: 2000-3000 tiny ones per 600 frames (palettes, 128 B-3 KiB), 35-48 ms per
  600 frames = 0.07 ms/frame. Not worth a fix.
- What is big: the released list churns 5-10 GiB of **render targets** per 600 frames (released-bytes sweep) and
  0.9-4.4 GiB of "replaced at address" destroys, with 660-920 entries at the 3 GiB cap. These are not uploads
  (render targets are not mirrored) but each is a vkCreateImage + allocation + alias copy of a transient target the
  game finalizes and re-creates; `vk_defer_image` frees run on the completion thread. A cap keyed by count of
  render targets per (format, size) class, or keeping the newest released entry per address instead of FIFO oldest
  overall (LRU by take-back), would cut that churn; measure with `perf: frame N: texture aliases` first.
- Proposed if the play log confirms scene loads: content-addressed image parking (hash at upload time, sampled hash
  index at create, adopt the parked VkImage in `create_tex` for an identical `VkImageCreateInfo`), capped by bytes;
  saves the upload of textures shared between areas (the 12 MiB "other key" share here says little is shared within
  one scene; across areas it is unknown). Not implemented: the replay did not show the problem.
