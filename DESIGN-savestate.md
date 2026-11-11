# Save states: design and verdict (2026-11-11)

Verdict: a full save state (save at frame N, load in a fresh process) is **not feasible** in this runtime without
rewriting how lifted code calls and returns. Nothing was built upstream; no knob, no `state.req`, no `lab-run --state`.
The GPU half of the idea is fine; the CPU half is what breaks it.

## What state exists, and where

| State                                                                       | Where                                                                                                                                    | Serialisable?                                        |
| --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| Guest RAM (heap, alias region, module .data/.bss, guest stacks, patch page) | `memory.c` reservations at fixed guest addresses below 2^39                                                                              | yes: committed pages, plain bytes                    |
| GPU memory                                                                  | NVN pools are guest memory; shadow buffers/mirrors are copies (`vk_memory.c`)                                                            | yes: rebuild from guest RAM as at boot               |
| Textures, pipelines, samplers, descriptors                                  | `vk_texture.c`, `vk_pipeline*`, keyed by guest descriptors                                                                               | rebuildable lazily from guest RAM + NVN objects      |
| NVN front-end objects (pools, textures, queues, command buffers, syncs)     | host heap structs in `nvn_api_*.c`, reached from guest memory by **host pointer** or handle                                              | only with a pointer-fixup pass per type (~545 procs) |
| Guest thread registers                                                      | `Cpu` per thread / fiber (`runtime/cpu.h`): x0-x30, sp, pc, nzcv, v0-v31                                                                 | yes, but not sufficient (below)                      |
| **Guest call stack**                                                        | **the host stack** of each guest thread/fiber: 256 MiB `mmap(NULL, ...)` per thread (`kernel.c:5`, `HOST_STACK`; `platform/linux.c:335`) | **no**                                               |
| Kernel objects (handles, events, waiters, priorities, fibers)               | `kernel.c` statics (`RtThread`, `Fiber`, global lock G)                                                                                  | yes in principle                                     |
| IPC sessions, `audren:u`, hid, fs working copy, timers, frame pacing        | `ipc.c`, `audren.c`, `ov_input.c`, `fs_host.c`, `frame_rate.c` statics                                                                   | yes in principle, each by hand                       |

## Why the CPU half cannot be serialised

1. **Every guest `BL` is a host call** (`kernel.c:5`): lifted functions are C functions; a guest call chain is a chain
   of host frames holding host return addresses, spilled host pointers (`Cpu *`, `RtThread *`, malloc'd runtime
   objects) and host callee-saved registers. The `Cpu` struct only holds the innermost guest registers; `pc` is set only
   for indirect dispatch. There is no guest-level representation of "where thread T is" to save.
2. **Host stacks are at ASLR'd addresses** (`mmap(NULL, ...)`) and so are the binary, libc and every heap object those
   frames point to. A fresh process cannot place them identically.
3. **At any frame boundary, all ~30 guest threads are parked inside host code**: `pthread_cond_wait` under kernel.c's
   lock G, inside an NVN call into the Vulkan back end, in `audren` mixing, or in a fiber switch. Their innermost frames
   are glibc/driver frames, not guest frames. There is no point where every thread is "between guest instructions" with
   an empty host stack (unlike an interpreter or a JIT with guest-memory stacks).
4. Copying host stacks verbatim therefore requires restoring the whole process (threads, TLS, libc, heap): that is
   CRIU. CRIU is not possible here: the container has no `CAP_CHECKPOINT_RESTORE`/`CAP_SYS_ADMIN`/`CAP_SYS_PTRACE`
   (CapEff 0x800405fb), the process holds a userfaultfd and a Wayland/display socket, and with a real GPU the driver's
   kernel objects (the 2026-11-09 finding) cannot be checkpointed. Under `LAB_SOFT` lavapipe the driver is pure user
   memory, so only the first three block it there.

The GPU half (restore guest RAM, drop host GPU objects, re-create from guest memory as at boot) would work: the texture
cache already rebuilds entries from storage (`entry_of`, stale/gone rules) and pipelines come from the cache keyed by
shader hash.

## What a full version would need (not proposed)

A recompiler change so guest control flow lives in guest memory: lifted code returns to the dispatcher instead of
nesting host calls (trampolined calls, guest LR as a guest address, `rt_dispatch` loop), host calls only at leaf SVC
/override boundaries that a thread can be parked before. Then a frame-boundary quiesce (every thread parked at an SVC
entry with `Cpu` complete) plus per-module serialisers for kernel, IPC, NVN objects (pointer fixups), audio and input.
That is an upstream-scale redesign of `recomp/` and `kernel.c`, and costs speed on every call.

## Partial versions that work today

- **Game save + replay (what exists).** A recording bundle (`just play` copies saves; `lab-run <rec> <frames>`) boots
  from the game's own save slot and replays input. Positions drift once the player moves (ARCHITECTURE 8), so only
  standing-still windows are comparable. This is the honest "save state" of this runtime.
- **Memory-only snapshot for analysis.** Dumping committed guest RAM at a frame (as `find.req`/`peek.req`, 0055/0071,
  already read it under `mem_read_hold`) is feasible and safe, for offline diffing; it cannot be loaded back.
- **In-process RAM rewind** is not safe either: restored guest stacks and heap would disagree with the live host stacks
  and runtime objects (point 1).
