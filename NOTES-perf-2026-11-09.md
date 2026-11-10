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

## After fixes 1+2 (2026-11-09 evening)

Trace `~/claude/kak-starting-at-3:20.tracy` (Tracy 0.13.1, 183 MB, 297 s; `~/claude/ya.tracy` is its first 167 s),
`build/v111/nx2navi.tracy` rebuilt 19:11 with patch 0024 (GPU-only wait for the submit finish wait and the LOD guard,
`NX2NAVI_GPU_WAIT` on) and 0025 (write-back compare on a 4-thread pool, lists under 4 MiB inline); dedupe and LRU off.
Play log `play-20261109-191317.log`. Same method; scripts `perf-scripts/an6.py` (loader), `rep6.py` (windows),
`anat.py` (offsets inside the frame), `gaps.py` (replay thread) in the scratchpad, exports in `perf-after2/`.
Threads here: t7 game, t6 replay, t3 completion, t5 audio, t4 producer. The pool workers have no zones.

**Not the same conditions as the before traces.** `nx2navi.ini` has `fps_limit = 60` in this run (the field before
ran with 240, Kakariko before with 60); the limiter never engages in either area (pacing 0.0, every frame over
16.7 ms), so it does not matter here. The field view is heavier than this afternoon's: 687 binds and 1002 touched
pools per frame against 608 and 770 (the before trace itself ran 30 ms at 613 binds for 20 s before it settled at
22.9). Differences of 2-3 ms between the runs are scene, not patches.

**Segments** (trace time, s): menu at 60 fps until 60; field load 62.0-63.4 (704 + 331 + 341 ms, 2.1 GiB);
**field, standing: 105.0-185.0** (80 s, 3111 frames; 66-93 is the same within 0.4 ms; 95-104 is a 60 fps
interlude with ~100 binds, a menu, left out); leaving 185-190; Kakariko load 190-194 (one 146 ms frame, 293 MiB);
**Kakariko: 200.0 (Cal's 3:20) to 297.3**, of which **running 200-240** (4.4 GiB uploaded), standing 240-265
(heavy view) and standing 265-end (light view). The before Kakariko window was running throughout, so the
running part is the like-for-like one.

The play log's shadow line is only printed at frames 600 and 1800 (menu, "0 pooled + N inline", 0.1 MiB), in this log
and in the before logs, so pooled vs inline comes from the zone values (a list of 4 MiB or more is pooled).

### 1. Frame time, before vs after

| window | frames | mean ms | p50 | p90 | p99 | max | mean fps | >16.7 ms | >33 ms |
|---|---|---|---|---|---|---|---|---|---|
| field before (ya.trace, last 30 s) | 1310 | 22.90 | 22.97 | 25.08 | 27.36 | 31.62 | 43.7 | 1310 | 0 |
| **field after (105-185 s)** | 3111 | 25.71 | 25.87 | 28.13 | 30.41 | 37.42 | 38.9 | 3111 | 3 |
| field after, last 30 s of it (155-185) | 1172 | 25.59 | 25.67 | 28.14 | 30.61 | 36.63 | 39.1 | 1172 | 2 |
| Kakariko before (kak, 30 s-end, running) | 1991 | 28.07 | 27.16 | 37.06 | 50.47 | 65.54 | 35.6 | 1982 | 407 |
| **Kakariko after, running (200-240 s)** | 1340 | 29.84 | 27.88 | 39.21 | 57.19 | 110.78 | 33.5 | 1340 | 334 |
| Kakariko after, all (200-297 s) | 3656 | 26.61 | 24.77 | 34.67 | 49.46 | 116.58 | 37.6 | 3653 | 512 |
| Kakariko after, standing heavy (240-265) | 824 | 30.35 | 30.16 | 35.42 | 43.58 | 116.58 | 32.9 | 824 | 176 |
| Kakariko after, standing light (265-end) | 1492 | 21.65 | 21.87 | 24.07 | 26.11 | 46.85 | 46.2 | 1489 | 2 |

No gain: the field is 2.8 ms slower (heavier view), Kakariko running 1.8 ms slower. The play log agrees (42.2,
40.0 and 34.7 fps for its three 60 s periods). Kakariko quiet frames 27.6 ms (before 26.3), movement frames (over
1 MiB of uploads, 17%) 40.7 ms (before 35.6, 19%): 19.9 MiB per movement frame against 10.0.

### 2. Zone cost per frame, before vs after (ms; share of 4.17 / 16.7 ms for the after value)

| zone | thread | field before | field after | of 4.17 / 16.7 | Kak before | Kak after (running) | of 4.17 / 16.7 |
|---|---|---|---|---|---|---|---|
| submit finish wait | game | 5.07 | 7.21 | 173% / 43% | 5.35 | 4.91 | 118% / 29% |
| write-back compare | completion | 5.41 (162 zones, 66.0 MiB) | 4.15 (3 callbacks, 66.3 MiB) | 100% / 25% | 5.09 (157, 60.6 MiB) | 4.39 (3, 60.6 MiB) | 105% / 26% |
| write-back | completion | 0.36 | 0.42 | 10% / 3% | 0.52 | 0.64 | 15% / 4% |
| shadow sync | replay | 2.71 (770 pools) | 3.42 (1002 pools) | 82% / 20% | 2.81 (746) | 3.98 (759) | 95% / 24% |
| bind pipeline (count) | replay | 608 | 687 | | 645 | 642 | |
| texture upload, first-time | replay | 0 | 0 | | 0.47 (1.56 MiB) | 0.71 (2.19 MiB) | 17% / 4% |
| texture upload, re-uploads | replay | 0.06 | 0.07 | 2% / 0% | 0.29 (0.35 MiB) | 0.64 (1.16 MiB) | 15% / 4% |
| audio mix | audio | 1.39 (0.30 per mix) | 1.51 (0.29) | 36% / 9% | 2.92 (0.52) | 3.29 (0.55) | 79% / 20% |
| nvn submit | producer | 0.13 | 0.15 | 4% / 1% | 0.17 | 0.19 | 5% / 1% |

Write-back compare, pooled vs inline (after): one list of 4 MiB or more per frame, pooled (66.2 MiB in the field,
60.5 in Kakariko; 4.14 ms per call, p50 4.06, p99 5.41, max 9.18; Kakariko 4.38 / p99 7.00), and two lists per frame
inline on the completion thread (0.03 MiB each, 4-5 us). So 99.9% of the bytes go through the pool: the completion
thread t3 takes slice 0 and waits for the three `vk wb diff` workers inside the zone. Rate: 12.8 GB/s before on one
thread (14.7 for the big ranges), 16.7 GB/s on four (17.6 in the light Kakariko view, 12.9 in the heavy one). Four
threads buy 1.3x, not 3x: the compare reads 2 x 66 MiB in 4.1 ms = 32 GB/s, which is what the memory delivers
(inferred from the rate, the workers are not zoned).

### 3. Unzoned game-thread time

| window | frame | finish wait | unzoned game thread | before |
|---|---|---|---|---|
| field | 25.71 | 7.21 | 18.50 (72%) | 17.82 (78%) |
| Kakariko running | 29.84 | 4.91 | 24.93 (84%) | 22.71 (81%) |
| Kakariko quiet / movement frames | 27.6 / 40.7 | 4.51 / 6.85 | 23.1 / 33.9 | 21.2 / 29.1 |
| Kakariko standing, light view | 21.65 | 3.36 | 18.28 | |

### 4. Where the wait sits in the frame (this corrects section 3 above)

Offsets from the frame start (present), field, mean ms:

| event | before | after |
|---|---|---|
| write-back compares of the previous frame's GPU work (completion thread) | 6-14 (the big ranges 9.3-9.9) | 6.66-10.80 |
| game thread's first submit = finish wait starts | 16.35 | 16.55 |
| finish wait ends (the two tiny compares follow it) | 21.42 | 23.76 |
| the producer's 4 submits, the game thread's second | 22.0 | 24.5 |
| binds issued by the replay thread while the game thread waits | 134 of 608 | 234 of 687 |
| from the last of those binds to the end of the wait (GPU) | 2.85 | 2.89 |

The finish wait and the write-back compare **never overlapped**: 0.01 ms of overlap per frame before and after, in
both areas. The compare of a frame's 66 MiB runs 6-11 ms into the next frame, when the GPU has written; the wait
starts at 16.5 ms. Section 3's reading of `completion_main` was right about the code and wrong about the timing: the
callbacks due before the first submission's value are two tiny lists.

What the game thread waits for is the **replay thread**. It is still recording the previous frame's draws when the
first submission of the next frame arrives 16.5 ms later (a third of the frame's binds are issued during the wait),
then records that submission, then the GPU needs 2.9 ms. The play log's worst field frames say the same: `replay`
(recording time between two presents) 32.4 of 37.5 ms, 35.2 of 37.4, 27.6 of 32.8, 29.2 of 32.9. The replay thread
is saturated; `frame bound ... 0 waited` only said the present never waits, the finish wait is where the game does.
Frame = replay recording of one frame (~21-22 ms in the field) + GPU 2.9 + the 2 ms from the wait to the present.
The game thread's own 16.5 ms before its first submit runs in parallel and is the second limit.

Replay thread per frame (field after, 25.7 ms): zoned 3.6 (shadow sync 3.4); gaps under 0.2 ms between its zones
(draw recording between binds) 9.6; gaps of 0.2-1 ms 5.3 (11.8 per frame, one per part: 11.4 parts); gaps of 1-3 ms
7.1 (4.4 per frame). Of the long gaps the log names one: `vk: texture pool sets: ... 0.172 ms catch-up and 3.126 ms
entry refresh per switch (32886 slots, 16786 refilled: ... 16606 address changes ...)`, about one switch per frame,
3.8 ms as the mean over 7200 switches (so ~4.5 in Kakariko), with `120574916 slot invalidations` per 3600 switches
from 145 k take-backs and 145 k releases: the released-list churn of render targets re-fills half of the 32 k
texture-pool slots every frame.

### 5. Verdict per fix

| fix | did it do what it was for | frame gain |
|---|---|---|
| 0024 GPU-only wait | Nothing to remove: the compare was not inside the wait before (0.01 ms overlap). The wait is 7.2 ms in the field (5.1 before, more binds behind it) and 4.9 in Kakariko (5.4). | 0 ms, 0 fps |
| 0025 pooled compare | Yes, modestly: 5.41 -> 4.15 ms per frame in the field (-23%), 5.09 -> 4.39 in Kakariko running (-14%), 162 zones -> 3 callbacks; memory-bound at 16.7 GB/s. | 0 ms, 0 fps: the completion thread is not on the frame's path |

Both are harmless and stay; neither was the bottleneck. Field 43.7 -> 38.9 fps and Kakariko running 35.6 -> 33.5 fps
are scene differences (binds, pools, 2x the upload bytes per movement frame), not regressions the zones can pin on
the patches: unzoned game-thread time and the GPU tail are unchanged per bind.

### 6. What dominates now, and the next two fixes for "stable 60 fps, p99 under 16.7 ms"

The replay thread's recording time per frame (~22 ms field, more in Kakariko), then the game thread's own 16.5-18.5 ms
(field) and 23-25 ms (Kakariko running).

1. **Make the replay thread cheaper, starting with what is already measured.** (a) The texture-pool entry refresh,
   3.1-4.5 ms per frame: stop the released-list take-back/release of render targets from bumping the buckets (keep a
   slot's view when the same image comes back at the same address, or bump per entry and not per bucket), so a
   switch refills hundreds of slots and not 16.8 k. (b) Shadow sync, 3.4-4.0 ms and ~1000 pools per frame: item 4 of
   the list above, now on the critical path. (c) The 0.45 ms per part between zones (11.4 parts): zone
   `replay submit` / `part submit` / pool sync first (section 5 of the zone list), then cut. Expected: every ms off
   the recording comes off the finish wait 1:1 until the wait is gone, so up to 7.2 ms in the field (25.7 -> 18.5 ms,
   54 fps) and 4.9 ms in Kakariko. Upper bound at no cost: `NX2NAVI_SUBMIT_FINISH=0 just play` for a minute in the
   field (risk: white dialogue frames).
2. **The game thread's 16.5 ms before its first submit** (18.5 unzoned per frame in the field, 23-25 in Kakariko):
   the floor once the wait is gone, and above 16.7 ms on its own. Unmeasured still: sample it (`perf record -t` on
   the render thread, or Tracy sampling) to split guest code, NVN API cost and blocking, and add the `nvn block`
   zones. 60 fps needs this under ~14 ms; nothing in the zones says yet whether that is reachable.

After those: Kakariko's movement frames (40.7 ms; 121 frames over 40 ms in 200-240 s, the block at 219.4-223 s with
50-98 MiB of uploads per frame, 60-111 ms, finish wait 1 ms: an area load on the route) decide the p99 there; the
upload path item of the Kakariko list stands. Shrinking the written ranges (item 3 of the first list) no longer buys
frame time, only completion-thread time.

## Guest optimisation level (2026-11-09 night)

Question: what does a higher optimisation level for the lifted game code buy? It is compiled at `-O1`
(`build-linux.py`, upstream: "its size makes -O2 slow to build"), `-march=x86-64-v3`, no LTO or PGO. **Answer:
nothing measurable; the default stays `-O1`.** `-O2` is not slow to build here, but the frame does not get shorter
and the guest threads do not use less CPU.

Setup: a clean source tree `~/claude/nx2navi/NX2navi-opt` (detached at `build` 14db217, so the runtime is the same
in every variant), its own lift copy and out dir, the game's caches reflink-copied; one binary per variant
(`nx2navi.o1`, `.o2`, `.o2n`), only the guest flags differ. Lab replay of `input-20261109-191317.txt` with the
`just play` environment, `NX2NAVI_TRACE=perf,present`, `NX2NAVI_GPU_WAIT=0`, `NX2NAVI_FPS_LIMIT=240`, windows in the
recording's game ticks (from the `input: script frame F tick T` lines). **Field, standing: ticks 6300-10200** is the
only valid window: the Kakariko part of this recording goes out of sync within seconds (Cal watched it), and two runs
of one binary differ by 7 fps there. CPU per thread from `/proc/<pid>/task/*/stat` sampled every 2 s over the window
(scripts in `NX2navi-opt/gopt-scripts/`: `lab.sh`, `an.py`, `sampler.py`, `cpu.py`).

| variant (guest flags) | build, wall | 5 slowest TUs | binary | field fps | p99 ms | replay thread ms/frame | guest main CPU ms/frame | all guest threads CPU ms/frame |
|---|---|---|---|---|---|---|---|---|
| A `-O1` (today) | 304 s (lift, runtime, 551 guest TUs) | main_0282 84 s, 0240 70, 0203 60, 0255 59, 0202 59 | 318 MB | 41.0, 39.6, 38.8 (three runs) | 28.9, 29.9, 33.4 | 20.7-21.7 | 7.20 | 54.98 |
| B `-O2` | 381 s (lift, guest) | main_0282 109 s, 0284 72, 0272 63, 0089 63, 0044 62 | 324 MB | 41.9, 40.5 | 28.7, 29.6 | 20.2-21.0 | 7.10 | 54.99 |
| C `-O2 -march=znver3` | 332 s (lift, guest) | main_0282 98 s, 0284 64, 0272 56, 0255 48, 0240 47 | 325 MB | 39.0, 40.3 | 32.3, 32.7 | 21.1-21.4 | 7.12 | 54.85 |
| D PGO | not built | | | | | | | |

Build times are on 32 threads at niceness 19 with other agents' compiles beside them (so B against C is noise); no
translation unit is pathological at `-O2`, nothing needs to stay at `-O1`. `-march=native` cannot be passed: the Nix
clang wrapper drops it, so the CPU is named (`znver3` for the 5950X). Kakariko, indicative only: 40 and 46 fps at A,
52 at B, 49 at C, inside the spread of the desync.

Why nothing moves:

- The frame is the **replay thread**: 21 ms of recording per 24-26 ms frame, 21-22 ms of CPU per frame on `vk replay`
  and 12 on `vk recorder`. That is runtime code, already at `-O2`, the same objects in every variant. This is section
  4 of "After fixes 1+2" again.
- The lifted code runs on about 25 guest threads. The busiest, `guest main`, uses 7.1-7.2 ms of CPU per frame, the next
  five 5.7-6.4 ms each; none is near the 25 ms frame. Their sum, 55 ms per frame, is the same to 0.2 ms in all three
  variants, and the CPU of a guest thread also covers the runtime's NVN, kernel and service code that it calls, which
  the guest flags do not touch. `-O1` already does the inlining and register allocation that matters for
  machine-lifted code (loads and stores through the guest memory base with `-fno-strict-aliasing`); `-O2` adds
  vectorisation and more aggressive inlining, for which that code offers nothing.
- So **PGO was skipped**: there is no guest hot spot on the frame's path for a profile to improve, and an instrumented
  build plus profile replay would cost about 15 minutes of lab time for a number that cannot show. It becomes worth a
  look only once the replay thread is under ~10 ms and a guest thread is what the frame waits for; the plumbing is
  ready (`--guest-flags=-fprofile-generate --link-flags=-fprofile-generate`, then
  `--guest-flags=-fprofile-use=<merged.profdata>`).
- Castle slot and crash spot were not re-run per variant: no variant is adopted, and all three replayed the 19:13
  recording through the menu, the field and into Kakariko.

No `nx2navi.opt` was delivered: no variant is measurably better.

Tooling that stays (commits 25bbd3e, fae6fd8, f41e756):

- `build-linux.py --guest-opt 1|2|3`, `--guest-flags '...'`, `--guest-obj NAME`, `--link-flags '...'`; `just game`
  reads `NX2NAVI_GUEST_OPT` and `NX2NAVI_GUEST_FLAGS`. The default is unchanged and its objects stay in
  `obj/{main,sdk,subsdk0}`; any other variant has `obj/guest-<tag>/` (`guest-O2`, `guest-O2-znver3`), so switching
  between variants only relinks.
- **ccache** (flake package) in front of clang through a PATH entry, so ninja's command lines are as before and
  nothing was rebuilt. Cache: `~/claude/nx2navi/.ccache` (gitignored, 40 GB limit, 0.1 GB now, compressed). Checked:
  the `-O2` guest built into a new object folder, 342 s and 557 misses; the same again into another folder, 52 s
  and 557 hits, 0 misses (the 52 s are the lift step, which always runs: about 45 s).
- Rebuild times in `NX2navi-opt`: nothing changed 54 s; one lifted file touched 58 s (one compile, link). Both are
  the lift step plus a link; the kit's two bring-up fixes rewrite their files on every lift, which ccache now absorbs.
- The lift step runs with `OPENBLAS_NUM_THREADS=1`: 32 workers with 32 BLAS threads each hit the container's 2048
  task limit once and the lift hung on `pthread_create failed`.
- Kept on disk: `NX2navi-opt/build/v111/obj/guest-O1`, `guest-O2`, `guest-O2-znver3` (385-393 MB each), the three
  binaries, the lift copy (`NX2navi-opt/build/extracted`, 1.2 GB) and the reflink copies of the game caches (24 GB
  apparent, shared blocks: shader-cache 15 GB, pipeline-cache.bin 4.1 GB, mesa-cache 0.9 GB, shader and seed
  programs 1.2 GB). The tree is only needed to repeat this experiment; `git -C NX2navi worktree remove NX2navi-opt`
  drops it.

## Round 3 (2026-11-09 night)

Side binary `build/v111/nx2navi.new` (and `nx2navi.new.tracy`), patches 0030, 0035, 0036; nothing swapped. Lab replays
of `input-20261109-191317.txt` with the `just play` env (`REPLAY_ASYNC=1 VK_RECORDER=1 TEX_RELEASED_MIB=3072
GPU_WAIT=0`, ini limit 60), `NX2NAVI_TRACE=perf,present`. **Only the field standing window (105-185 s of summed
present intervals) is a valid measure**: Cal watched a replay and the Kakariko part leaves his path at once.

**Why replays drift, and what a deterministic mode needs.** `frame_rate.c` advances game time (`game_us`) by the
measured wall interval of each present and `input.c` keys the recording to 60 Hz ticks (or world-clock ms) of that
time. Every replay has other frame intervals, so the game steps with another dt per frame and reads the stick at other
instants; positions diverge and add up. A "timedemo" mode would step game time by a fixed amount per presented frame
(or by the recording's own per-present dt, logged by present index), key inputs to the present index, and report
presents per wall second. Not built.

### 1. Texture-pool entry refresh (patch 0030, both switches default 0)

| run (field window) | fps | mean ms | p99 ms | entry refresh ms/switch | slots refilled (wrote nothing) | shadow sync ms/frame |
|---|---|---|---|---|---|---|
| `TEX_STATE_GEN=0` | 42.7 | 23.41 | 28.66 | 2.66 | 17196 (13564) | 2.80 |
| `TEX_STATE_GEN=1` | 43.1 | 23.18 | 29.40 | 2.67 | 13713 (10032) | 2.79 |

Kakariko window (indicative only, out of sync): 53.4 -> 55.2 fps, refresh 3.08 -> 2.93 ms.

- State generations: 93% of the address bumps return to a known state (244k of 267k per 3600 switches), yet the refills
  only fall by a fifth and the time not at all. The slots still refilled are seen released at the submission's first
  sync and live again at a later one: real state changes, of which 10k write no descriptor.
- The split of the refresh (new `perf: texture pool` lines, the timers cost ~0.4 ms themselves): whole-table walk
  1.9-2.4 ms (in it the freshness checks 1.0-1.3 ms for 26k slots, 5.7k storage checks and ~1000 slots resolved again
  because they hold no entry), dirty walks 0.8-1.0 ms over 6-9k slots, refills 0.8-0.9 ms in both walks together,
  descriptor writes 0.2 ms. `TEX_CHECK_SKIP=1` (skip slots whose texture never uploads) takes under 0.2 ms off the
  checks.
- Graveyard (Cal's `play-20261109-215822.log`, 22 fps): 6.3 ms per switch with the same 32.9k slots and 13.8k refills as
  the field. The refresh does not scale with slots or refills; what grows is the per-texture storage check
  (`vk_mem_changed_snap` per mirrored entry, 7.4k live pins there) and the machine being busier.
- Checks: castle slot and crash spot pass with both switches on, castle picture clean beside the run with both off.
- Not done: shadow-sync batching. The sync is 2.8-3.1 ms per frame (915 pool syncs, 204-223 queries, 10 MiB copied);
  the write-watch queries of all consumers are 1.5 ms per frame (340-360 queries over 600 MiB). Next candidates, in
  order: the storage checks per submit by distinct entry and by written region instead of by slot; fewer write-watch
  queries (600 MiB queried per frame for 10 MiB copied).

### 2. Where the main thread's frame goes (patch 0035, `NX2NAVI_TRACE=nvn`)

The thread that presents (0x1008) is not the game loop: it sleeps in `svc 0x34` (WaitForAddress) 24.6 ms of a 25.9 ms
frame, woken by the main thread 0x1003 (sched trace: 91-95%), then submits 4 times and presents. The "16.5 ms before
the first submit" of the Tracy analysis is that sleep. Field window, run `r3-nvn4`, per frame of 25.9 ms:

| thread | entry | ms/frame | calls/frame | note |
|---|---|---|---|---|
| main 0x1003 | `nvnQueueSubmitCommands` | 9.26 | 2 | the submit finish wait (blocking) |
| | `svc 0x34` WaitForAddress | 7.91 | 23.5 | waits for its job workers, 0.34 ms each |
| | guest code | 4.12 | | the rest of the frame |
| | `svc 0xb` SleepThread | 1.40 | 239 | 5.9 us each |
| | `nvnCommandBufferCallCommands` | 0.68 | 563 | 1.2 us each |
| | `svc 0x1a` (lock) | 0.57 | 26.6 | |
| | `nvnCommandBufferAddControlMemory` | 0.57 | 26.4 | 21.5 us each |
| | all other host functions | ~1.1 | ~9900 | |
| workers 0x104d, 0x1050, 0x1051, 0x1052 (each) | guest code | 3.6-4.0 | | |
| | host functions | 1.5-1.7 | | CallCommands 0.5, AddControlMemory 0.45, EndRecording 0.14 |
| | SVC waits | 20.2-20.7 | | 0x34 17.9-18.6, 0xb 1.4-1.5, 0x1a 0.6 |

So of the main thread's frame: runtime 11.6 ms host functions + 2 ms of non-wait SVC cost against 4.1 ms guest code
and 7.9 ms waiting for workers that are busy 5.5 ms each (3.8 guest + 1.6 runtime). Guest code is 16% of the main
thread and 15% of a worker: the lifter and -O levels cannot buy the frame (the guest-opt A/B found the same). The
three largest runtime items and a fix each:

1. **Finish wait, 9.3 ms.** It waits for the replay thread to record and submit the frame's first submission, then
   for the GPU. See 3: only a cheaper replay thread shortens it.
2. **Job joins, 7.9 ms in 23 waits** against ~5.5 ms of work per worker: wake-up latency and the workers' own runtime
   cost (`AddControlMemory` 21-25 us per call on every thread, 80+ calls per frame: look at what it locks or maps),
   plus `svc 0xb`: 240 sleeps per frame per thread at 6 us (a yield that takes the scheduler lock; a spin of a few
   hundred ns before giving the core up would do). CCD pinning A/B: see 4.
3. **`AddControlMemory` + `CallCommands`, 1.25 ms on the main thread** and 1 ms per worker: command recording on the
   front end; `CallCommands` at 1.2 us for 563 calls is a copy per call, batchable.

### 3. The finish wait (patch 0036, `NX2NAVI_FINISH_DEFER`, default 0)

The game needs no result from the wait; it orders the GPU's reads of guest memory before the game's rewrites
(upstream's fix for white dialogue frames). With shadow storage the GPU reads the shadow, filled at each part's
submit, so the prototype returns once the submission is on the GPU and makes the replay thread wait for the GPU
before the next submission's shadow sync. Field window: 42.3 and 41.0 fps with the knob (the knob-0 runs of those
pairs ran beside other builds, load 17-23, and are void; clean baselines 42.7 and 43.1). The perf line still shows
8.6-8.7 ms of fence wait per frame: the wait is for the replay thread, which is ~one submission behind; the GPU is
busy 10.2 ms per frame. Castle and crash spot pass with the knob, picture clean. Frame = replay recording; the main
thread's 9 ms is its backlog.

THP: `/proc/<pid>/smaps` of a lab game shows every guest reservation with `nh` (MADV_NOHUGEPAGE) and `uw` (uffd
write-protect) and 0 AnonHugePages on all large mappings: guest memory is not THP-backed, host THP `always` vs
`madvise` does not matter for it.

### 4. One CCD or both (Ryzen 9 5950X, L3 per CCD: cpus 0-7,16-23 and 8-15,24-31)

Same binary and settings, `NX2NAVI_TRACE=perf,present,nvn`, the pinned runs through a temporary wrapper
(`taskset -c 0-7,16-23 ./nx2navi.new`, removed after), field window, 2026-11-10 01:21-02:10:

| run | fps | mean ms | p90 | p99 | main thread `svc 0x34` (worker wait) | finish wait | load during the run |
|---|---|---|---|---|---|---|---|
| default a | 42.6 | 23.50 | 26.70 | 29.01 | 7.61 ms | 8.38 ms | 8.8 (max 26) |
| pinned a | 42.2 | 23.67 | 26.09 | 27.83 | 7.69 ms | 8.17 ms | 9.1 (max 26) |
| default b | 43.0 | 23.27 | 26.50 | 28.66 | 7.58 ms | 8.17 ms | 5.3 |
| pinned b | 42.7 | 23.44 | 25.80 | 27.33 | 7.45 ms | 8.30 ms | 5.8 |

No change in the mean (-0.3 fps, inside the run-to-run spread) or in the worker wait (7.6 against 7.6 ms): the hand-offs
across the two L3 domains are not where the 7 ms go. The tail is tighter pinned: p99 -1.2 and -1.3 ms, p90 -0.6 and
-0.7 ms in both pairs, which fits Cal's impression of "steadier" (the lab cannot say "faster": the replay thread is the
bound either way). Keeping `NX2NAVI_CPUS=auto` in `just play` costs nothing measurable and trims the tail; with
other jobs on the machine (as in pair a) the pin also keeps the game off the cores they use only if those jobs are
kept on the other CCD.

## Runtime optimisation (2026-11-10 night, #148)

Question: does the runtime (the replay thread's code) get faster with -O3, znver3, ThinLTO? **Answer: no measurable
gain; the default stays `-O2 -g -march=x86-64-v3`.** `build-linux.py --runtime-flags` / `NX2NAVI_RUNTIME_FLAGS` build
a variant into `obj/runtime-<tag>` (ccache: 65-80 s for the runtime plus relink). Lab replay of
`input-20261109-191317.txt`, field standing window ticks 6300-10200, `taskset -c 0-7,16-23`, `NX2NAVI_TRACE=perf,present,nvn`
(scripts `.lab/rtopt/`).

| variant | build | fps | p99 ms | replay ms/frame |
|---|---|---|---|---|
| rt0 stock `-O2` | 65 s | 39.9, 43.3, 41.1 (sampled) | 29.1, 26.6, 27.1 | 21.4, 19.7, 20.7 |
| rt3 `-O3 -march=znver3` | 77 s | 41.2, 41.2 | 27.3, 27.3 | 20.7, 20.6 |
| rtl rt3 + `-flto=thin` (runtime objects only) | 80 s | 42.9, 25.9 (spikes, unexplained) | 26.2, 246 | 19.9, 28.6 |

All inside the 39.9-43.3 spread of the stock binary. PGO not built (no gain from step 2). `-fno-strict-aliasing` kept
(RT_FLAGS has it; not tested without). LTO over the 551 lifted files not tried.

Why: replay-thread profile (perf_event_open is denied in the container, so `tools/cpu-sampler.so`, a CPU-time timer
sampler, 500 Hz, 26k samples, rt0; window by wall time, indicative). 31% of the thread is libc/kernel the flags never
reach: `ioctl` 15.8% (GPU submit 4.9%, PAGEMAP_SCAN write-watch from `ww_query` 6.8%, RADV
`radv_update_preamble_cs` destroying and re-creating its preamble command streams on every submit ~3.5%), `memmove`
14.9% (shadow sync `vk_mem_shadow_sync` vk_memory.c:1097 and `shadow_sync_pool` 9.9%, `vk_exec_record` 2.0%). Then
`bind_resources` 7.1, `vk_texture_slot_khash_locked` 3.7, `put` (vk_rec) 2.7, `graphics` 2.5, `vk_texture_slot_token`
2.5, `shader_for` 2.1, memcmp 1.7, `pool_fill` 1.7, `resolve_locked` 1.6, `vk_usnap_find` 1.5, snprintf 1.5,
`find_stage` 1.4. The snprintf is `DUMP_ARGS` in op_draw/op_draw_idx (vk_exec_draw.c:4036): `vk_dump_armed` is set by
any `NX2NAVI_DUMP`, and lab-run always sets one, so lab replays pay ~2% replay CPU that `just play` does not.
Leads, none small enough for tonight: the RADV preamble rebuild per submit (why do ring sizes change each submit?),
fewer write-watch queries per sync, cheaper shadow copies.
