# NX2navi modding framework

Status 2026-11-11: layer (a) works for text (msgmod.py, the runtime's existing mod loader). Layers (b) to (d) are a
design, with a first RE database and a string cross-reference tool in place.

Boundary: game data and anything derived from it (message exports, string tables, addresses, the RE database) live
only under `NX2navi/build/` or `NX2navi/generated/` (NX2navi/AGENTS.md "Game content boundary"). This repo holds tools
and this design only.

## (a) RomFS overlay: already in the runtime

`runtime/mods.c` + `runtime/romfs.c` already implement player mods the emulator way, so no new loader is needed:

- one folder per mod under `NX2NAVI_MODS_DIR` (default `<dir of the binary>/mods`), with `<mod>/romfs`, the Atmosphere
  layout, or a mod manager's merged output; `NX2NAVI_MODS_ORDER` / `NX2NAVI_MODS_DISABLED` in nx2navi.ini [mods] (cfg.c
  rows exist); the top mod wins a path; the in-game menu toggles mods (applies at the next start).
- files are served by identity when the game opens them; the resource size table entries of the mods' files are
  raised automatically (`restbl_overlay`), so a file may grow.
- ExeFS `.ips`/`.pchtxt` become patch sets built at start (`tools/exefs_patches.py`); `exefs/subsdk*` code modules make
  the mod `MOD_PLUGIN` and keep it off: that is where (b) plugs in.

What the overlay does not do is unpack or recompress. That is tooling:

| format               | where                                                                                                  | tool                                                                                                   |
| -------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| zstd with dictionary | `*.zs`; dictionaries in `Pack/ZsDic.pack.zs` (a SARC of `.zsdic`), picked by the frame's dictionary id | `tools/msgmod.py` (`dictionaries`, `unpack_zs`), upstream `make_romfs_patches.py`                      |
| SARC                 | `Mals/*.sarc`, `*.blarc`, `*.pack`, `*.bfarc`                                                          | `sarc_nodes` / `sarc_replace` (same layout rule as upstream: old order, old alignment)                 |
| MSBT                 | `Mals/<lang>.Product.110.sarc.zs` members                                                              | `msgmod.py export/build`                                                                               |
| BYML                 | `*.byml(.zs)`                                                                                          | next: a small reader/writer (v7 BYML; `UI/LayoutArchiveCategory.byml` is loaded next to the Mals code) |
| BFLYT/BFLAN/BNTX     | layouts                                                                                                | upstream `make_romfs_patches.py` shows patch-in-place; a general repacker is out of scope for now      |

Findings that correct the brief: 1.1.1's MSBT files are UTF-8 (encoding byte 0), not UTF-16, and the player name is
not a tag: "Link" is literal text (777 times in 175 USen files); there is no naming step. The game's code still knows
`Mals/%s.utf_16.%s.sarc` and `utf_8` variants (f_7001175080), so other builds may differ.

MSBT control tags in the export: `{group.type:hexparams}` opens (0x0E), `{/group.type}` closes (0x0F); the meanings
found so far are `tag` rows in the RE database (2.x: variable insert by ASCII name such as `Shop_SelectItemPrice`,
0.3 colour, 0.4 page break, 4.0 voice, 5.x waits, 201.6 plural forms).

## (b) Runtime hook registry (design)

Every lifted function starts with `FN_ENTER(addr)` (`runtime/cpu.h`), today a predicted-false check of `g_fnprof`.
The registry generalises that one branch so hooks cost nothing when none is set:

```c
// runtime/hooks.h
typedef int (*RtHookFn)(Cpu *c, void *user);   // pre: return 1 to skip the original (replace); x0.. hold the result
int rt_hook_pre(uint64_t addr, const char *name, RtHookFn fn, void *user);
int rt_hook_post(uint64_t addr, const char *name, RtHookFn fn, void *user);
uint64_t rt_sym(const char *name);             // from build/v111/re/symbols.json (redb), 0 unknown
```

- FN_ENTER becomes `if (__builtin_expect(g_fnflags, 0)) { if (rt_fn_enter(a, c)) return; }`: one global, a sorted
  address table probed only when it is non-zero. Replace = pre hook returning 1. Functions are `void f(Cpu *)`, so an
  early return is legal C; the hook writes x0/v0 and restores sp/callee-saved state it touched (it is called before
  the prologue, so nothing is saved yet).
- Post hooks: the generator cannot cheaply wrap every return, so a post hook on `addr` swaps the caller's x30 for a
  trampoline address the dispatcher (`runtime/dispatch.c`) owns; returning through it runs the hook and resumes at the
  real x30. Direct C calls between lifted functions return by C return, not by x30, so the first version emits
  `FN_LEAVE(addr)` only in functions listed in a hooks file passed to `recomp/gen.py` (a rebuild per new post-hook
  site; pre/replace need none).
- Mods load as `.so` files: `<mod>/exefs/nx2navi-*.so` (Linux) dlopened after `rt_dispatch_init`, entry
  `int nx2navi_mod_init(const NxModApi *api)` with a versioned function table (hooks, memory API, log, cfg). This
  turns `MOD_PLUGIN` into a supported case for our own plugins; Switch `subsdk` NSOs stay off. The #166 overlay's
  dlopen loader is the same mechanism and should share code.
- Knobs: `NX2NAVI_MOD_PLUGINS` (0 default = off, old behaviour), with a cfg.c row.

## (c) Guest-memory API (design)

`runtime/boot.c` find.req / poke.req already scan mapped guest memory on a detached thread and write only into
read-write pages behind an `expect=` guard. The mod API wraps those primitives:

```c
typedef struct NxModApi {
    uint32_t version;
    int (*read)(uint64_t addr, void *out, size_t n);          // 0 when unmapped
    int (*write)(uint64_t addr, const void *in, size_t n, const void *expect);   // rw pages only, guarded
    size_t (*find)(const void *needle, size_t n, uint64_t *hits, size_t cap);    // all mapped memory
    int (*hook_pre)(uint64_t, const char *, RtHookFn, void *);
    int (*hook_post)(uint64_t, const char *, RtHookFn, void *);
    uint64_t (*sym)(const char *);
    void (*log)(const char *fmt, ...);
} NxModApi;
```

Writes from a hook run on the guest thread (safe); writes from a mod's own thread take the same per-present slot that
poke.req's keep=1 uses, so they never race the replay thread.

## (d) Symbol/RE database (started)

`build/v111/re/symbols.json` (derived, under build/), managed by `tools/redb.py`: one object per entry with `kind`
(function, host, struct, global, tag), `name`, `addr`, `confidence` (low/medium/high), `source` (strxref, msbt, a
runtime file, a session), `note`. `redb.py header` writes `symbols.h` (`SYM_<name>` addresses) for plugins;
`rt_sym` reads the JSON at start. `build/v111/re/seed.sh` recreates the seed.

Growing it:

1. string xrefs: `tools/strxref.py` maps every ADRP+ADD pair in the lifted C to the NUL-terminated string it points
   at (102k rows over main in 33 s, `build/v111/re/strxref.tsv`); `redb.py strings f_<addr>` lists one function's.
2. signature matching vs the lifted C (next): hash a function's lifted body with addresses masked, and match known
   open-source code compiled the same way (nn SDK, Havok, zstd, the eui/LMS message library) to name it.
3. live: fnprof (`g_fnprof`) hits with x0 tell which functions run on a given action; find.req tells where a shown
   string lives; a mark ties both to a moment.

## Next steps

1. Verify the text mod in the lab on the title menu (`text-demo` changes "Continue"); then a BYML tool.
2. hooks.c with pre/replace through FN_ENTER behind `NX2NAVI_MOD_PLUGINS`, plus the dlopen loader and NxModApi.
3. Signature hashing in strxref's walk; name the LMS message tag dispatcher (the function that switches on group
   0/1/2/3/4/5/201 near f_7001175080's callers).
