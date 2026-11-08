# Crash: the mesh stage's c0 storage table overruns the 2 KiB bank (stack overflow by 112 bytes)

**Version:** NX2navi 0.5.0, game 1.1.1 (kit lift), runtime built from main at 8702ddb for Linux (clang 23, SDL3 window).
**GPU:** AMD Radeon RX 6900 XT, RADV (Mesa 26.2.6), Linux 7.3. Reproduces at the same place every run.

## What happens

The first scene that draws with mesh shaders and bound storage buffers ends the process:

```
FATAL: access violation (0xb) at host 0x11a003f4 (nx2navi+0x118003f4), reading address 0x8
```

Host backtrace (gdb): `scratch(ex=0x0)` <- `c0_info` <- `ubo_info` <- `bind_resources` <- `prepare_draw_ex(mesh=1,
count=0x7fffffff)` <- `op_draw_mesh` <- `vk_exec_record` <- `vk_sync_submit` <- `nvnQueueSubmitCommands`. The log just
before: `vk: storage buffer bind, stage 6 slot 0` and `stage 7 slot 0/1`.

## Cause

`runtime/vk_exec_draw.c`: `c0_ssbo_base()` puts the mesh stage's storage table at 0x770, and `c0_table()` writes 16
entries of 16 bytes, so `vk_c0_fill()` writes bank[0x770 .. 0x870) into a `uint8_t tmp[VK_C0_BYTES]` of 0x800 bytes
(`c0_info`): 112 bytes past the end, onto the caller's stack frame. In the Linux build those bytes hold `ubo_info`'s
spilled `ex`; an unbound slot's zero address lands on it, and `scratch(ex)` faults on `ex->fence`. Confirmed with the
disassembly: `movq -0x30(%rbp), %rdi` before the `scratch` call, with `tmp` at -0x870(%rbp). On Windows the frame
layout differs, so the overrun hits something else (or nothing) there.

The task stage's table at 0x670 fits exactly (0x670 + 0x100 = 0x770); the mesh stage's does not. The comment above
`c0_ssbo_base` says the game binds slots 0-2 for those stages.

## Fix

Clamp the table to the bank, for example in `vk_c0_fill`:

```c
int base = c0_ssbo_base(stage);
if (base < 0) return;
int rows = (VK_C0_BYTES - base) / 16;   // 9 for the mesh stage at 0x770
c0_table_n(bank + base, ssbo, rows < 16 ? rows : 16);
```

or give `c0_table` the row count. `B.c0_in[k]`/`B.c0[k]` are unaffected (fixed sizes).

## Repro

Any mesh-shader draw with storage buffers bound. Input recording (`NX2NAVI_INPUT_RECORD`) from the title screen to the
crash on a 1.1.1 save, and `nx2navi.log`, attached.
