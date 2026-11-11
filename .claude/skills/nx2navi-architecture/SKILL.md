---
name: nx2navi-architecture
description: How NX2navi (the Zelda OoT Switch 2 static recompilation) is built and works - the lift from ARM64 to C, the guest/host boundary (SVCs, hooked nn:: functions, the NVN proc table), one frame from game thread to replay thread to Vulkan, the memory model, shader translation and caches, timing, and where each open problem sits. Use before changing or investigating anything in ~/claude/nx2navi or its NX2navi worktree, or when asked how NX2navi works.
---

# NX2navi architecture

The reference is `~/claude/nx2navi/ARCHITECTURE.md` (private repo; about 5,500 words, file references throughout). Read the sections your task touches before reading code; do not paste it into reports.

| Working on | Read section |
|---|---|
| Build, lifter output, flags, why a build differs from upstream | 2 Build pipeline |
| A call from game code into the runtime (kernel, SDK service, graphics) | 3 Guest/host boundary |
| What is the game's own code versus ours | 3 and 4 |
| Frame time, the replay thread, waits, ordering between passes | 5 One frame |
| Memory limits, refused maps, shadow sync, texture pins and caps | 6 Memory model |
| Texture cache: slot_resolve paths, released/live entries, VRAM knobs, RT recycle | 6, "Texture cache" |
| Shader translation, cache keys, pipeline builds, skip or wait, lowering bugs, invalid SPIR-V | 7 Shaders |
| Frame limit, game speed, replay drift | 8 Timing |
| Input, audio, HDR, upscaling, saves | 9 |
| Which private patch owns a knob | 10 Our private patches |
| cfg rows, clean builds, current recipes/exes, dumps, lavapipe runs, MSBT/text mods, BNTX swizzle | 11 Working rules and tooling |
| A term (NVN, SVC, shadow, pin, one-shot pass, c0/c1, patch page) | 12 Glossary |

Rules that follow from the architecture:
- Simulation and rendering are one to one, and game time follows wall time: a recording replays differently at a different frame rate. Measure only standing-still windows.
- The frame is bound by the replay thread (about 22 ms of translating and recording per frame). Work on the lifted game code, the GPU, or the main thread's waits does not raise the frame rate until that is cheaper.
- The game's code is lifted and never edited by hand. Change behaviour in the runtime, or through the patch table at generation time.
- Line numbers in the document drift after a rebase: trust file and function names, and correct the document when you find it wrong.

## Known pitfalls

- A new `cfg_bool`/`cfg_value` key without a settings-table row in `runtime/cfg.c` stops the game at start (FATAL `has no row`).
- Build variants only from a clean committed tree (worktree at a named commit); never over other agents' uncommitted edits.
- Texture slots can follow another entry at the same address (other size/format) or hit the stale rule: an unresolved or wrong-size texture is usually `slot_resolve`, not the shader. Read the `vk: slot ... follows` / `stale slot` log lines first.
- `TEX_RT_RECYCLE` and RT trims lose content when the game takes a render target back: flicker after a VRAM change points there.
- VMA block slack hides frees: driver VRAM usage does not fall when entries are destroyed.
- `NX2NAVI_WATCH` is GPU-side; CPU counters need gdb or `/proc/pid/mem`.
- Before telling Cal a command, check the justfile recipe and its default exe.

Keep it current: when a finding changes how a subsystem is understood, edit the matching section of ARCHITECTURE.md in the same change, before you finish (the feed alone is not enough).
