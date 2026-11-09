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
