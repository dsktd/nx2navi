# NX2navi on the desktop, every step inside the flake's shell. Settings by environment or on the command line:
#   just src=~/claude/nx2navi/NX2navi ver=v111 build   (the defaults; src is a worktree of ~/claude/.bare/NX2navi.git)
#   NX2NAVI_GPU=nvidia just run                 (NVIDIA host driver through nixGL; Mesa is the default)
#   NX2NAVI_NUP=/path/game.nup just extract     (the dump as a .nup: no keys needed; or just nup=/path/game.nup extract)

set shell := ["bash", "-euo", "pipefail", "-c"]

src := env("NX2NAVI_SRC", justfile_directory() / "NX2navi")
ver := env("NX2NAVI_VER", "v111")
gpu := env("NX2NAVI_GPU", "mesa")
# mesa=stable: Vulkan through nixpkgs stable's Mesa (25.2.6) instead of unstable's, see flake.nix
mesa := env("NX2NAVI_MESA", "")
shellname := if mesa == "stable" { "#mesa-stable" } else { "" }
# Which draws are skipped while their pipeline builds (upstream default fullscreen): strict waits for full-screen
# draws, which with the pipeline library off otherwise go black while they build
pipeskip := env("NX2NAVI_PIPE_SKIP", "any")
nup := env("NX2NAVI_NUP", "")
# The lifted game code's optimisation level (1, 2, 3; empty = build-linux.py's default) and extra compile flags for it,
# e.g. NX2NAVI_GUEST_OPT=2 NX2NAVI_GUEST_FLAGS=-march=znver3 just game. Each variant keeps its own objects
# (obj/guest-<tag>), so switching only relinks. NOTES-perf-2026-11-09.md "Guest optimisation level"
guestopt := env("NX2NAVI_GUEST_OPT", "")
guestflags := env("NX2NAVI_GUEST_FLAGS", "")
# Extra compile flags for the runtime (stock -O2 -g), e.g. NX2NAVI_RUNTIME_FLAGS="-O3 -march=znver3" just game;
# objects in obj/runtime-<tag>. NOTES-perf-2026-11-09.md "Runtime optimisation"
rtflags := env("NX2NAVI_RUNTIME_FLAGS", "")
# the Steam Deck's hostname or IP for `just deck`
host := env("NX2NAVI_DECK", "")

# The live screensaver's job registry (claude-job in the container): a run registers itself so the Director's
# jobwatch scene shows its log and frame count; removed when the run ends
jobs_dir := env("HOME") / "claude/.services/screensavers/jobs"
# the [work] dir of config.local.toml (where build_game.py looks for extracted/<ver>)
work := env("NX2NAVI_WORK", "build")
# make_game.py insists on an MSYS2 folder before it starts, although the extraction never uses it: an empty stand-in
msys := justfile_directory() / ".msys-stub"
flake := justfile_directory()
impure := if gpu == "nvidia" { "--impure" } else { "" }
wrapper := if gpu == "nvidia" { "nixVulkanNvidia" } else { "nixVulkanIntel" }
# RADV (Mesa 26.2.6) segfaults in its graphics pipeline library path while this game builds pipelines
# (libvulkan_radeon.so+0x19be92, found 2026-11-08 on an RX 6900 XT); without it the runtime builds whole pipelines
# SDL otherwise picks X11 (XWayland) on the desktop; the game is a plain Wayland client
# SDL_JOYSTICK_HIDAPI_STEAM=0: SDL must not drive the Steam Controller itself (its hidraw nodes are open on the desktop);
# yakin owns it and presents the pad SDL sees
# (NX2NAVI_FIX_C0=0 avoids the mesh-stage c0 overflow crash, upstream-issue-c0-mesh.md, but the picture goes black:
# the shaders read zeros for their driver constants. Not usable; the fix has to land upstream.)
radv := "SDL_VIDEODRIVER=" + env("SDL_VIDEODRIVER", "wayland") + " SDL_JOYSTICK_HIDAPI_STEAM=0 " + (if mesa == "stable" { "" } else { "RADV_DEBUG=nogpl " }) + "NX2NAVI_PIPE_SKIP=" + pipeskip
dev := "NX2NAVI_NVIDIA=" + (if gpu == "nvidia" { "1" } else { "0" }) + " nix develop " + impure + " " + flake + shellname + " --command"
py := ".venv/bin/python"
py314 := ".venv-py314/bin/python"

[private]
default:
    @just --list --unsorted

# Everything from the .nup to a playable build: venvs, extract, xlate, game (lift, glue, compile), shaders
build: venvs extract xlate game shaders

# A worktree of the bare clone in ~/claude/.bare at {{src}}, branch build on origin/main
worktree:
    test -e "{{src}}/.git" || git -C ~/claude/.bare/NX2navi.git worktree add "{{src}}" -b build --track origin/main

# Write config.local.toml from the example. With a .nup only [work] dir matters; set NX2NAVI_WORK to the same value
config:
    test -e "{{src}}/config.local.toml" || cp "{{src}}/config.example.toml" "{{src}}/config.local.toml"
    @echo "edit {{src}}/config.local.toml: [work] dir (and, without a .nup, base, updates, keys with POSIX paths)"

# The two Python environments, from the Nix interpreters
venvs:
    cd "{{src}}" && {{dev}} bash -c '\
        uv venv -q --python 3.12 .venv && uv pip install -q --python {{py}} -r tools/requirements.txt zbic && \
        uv venv -q --python 3.14 .venv-py314 && uv pip install -q --python {{py314}} -r tools/requirements-py314.txt'

# hactool, patched and built from source
hactool:
    cd "{{src}}" && {{dev}} {{py}} tools/build_hactool.py

# Only check that the .nup is Ocarina of Time 1.1.1
check:
    test -n "{{nup}}" || { echo "set NX2NAVI_NUP (or nup=...) to your .nup"; exit 1; }
    cd "{{src}}" && {{dev}} {{py}} -I tools/make_game.py --nup "{{nup}}" --check

# Unpack the .nup into {{work}}/extracted/{{ver}} (about 30 GB); without a .nup, extract.py with the config's dump and keys
extract:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{src}}"
    if [ -z "{{nup}}" ]; then exec {{dev}} {{py314}} tools/extract.py; fi
    mkdir -p "{{msys}}/bin" "{{msys}}/lib" "{{msys}}/include/vma"
    touch "{{msys}}/bin/clang.exe" "{{msys}}/bin/clang++.exe" "{{msys}}/bin/SDL3.dll" "{{msys}}/lib/libSDL3.dll.a"
    {{dev}} {{py}} -I tools/make_game.py --nup "{{nup}}" --out "{{work}}/extracted/{{ver}}" --until romfs --msys "{{msys}}"

# The shader translator (.NET)
xlate:
    cd "{{src}}" && {{dev}} env GIT_CEILING_DIRECTORIES="{{src}}" {{py}} tools/build_xlate.py

# Lift (the kit, with its bring-up fixes), glue, compile and link build/{{ver}}/nx2navi (a CPU without AVX2: just game v2).
# tracy=1 builds build/{{ver}}/nx2navi.tracy with the Tracy profiler client instead (README "Profiling with Tracy")
game cpu="v3" tracy="":
    cd "{{src}}" && {{dev}} python3 -I "{{flake}}/build-linux.py" --src "{{src}}" --extracted "{{work}}/extracted/{{ver}}" --out "build/{{ver}}" --cpu {{cpu}} {{ if tracy != "" { "--tracy --exe nx2navi.tracy" } else { "" } }} {{ if guestopt != "" { "--guest-opt " + guestopt } else { "" } }} {{ if guestflags != "" { "--guest-flags=" + quote(guestflags) } else { "" } }} {{ if rtflags != "" { "--runtime-flags=" + quote(rtflags) } else { "" } }}

# Prepare every shader of the game files and warm the GPU driver's cache (opens a window: run from the desktop session)
shaders: && fmzpow
    cd "{{src}}" && {{dev}} env {{radv}} {{wrapper}} {{py314}} tools/prepare_shaders.py build/{{ver}} --romfs "{{work}}/extracted/{{ver}}/romfs" --exefs "{{work}}/extracted/{{ver}}/exefs" --no-list

# The real fix (NOTES-fog-nan.md): NVIDIA's pow is LG2, FMUL.FMZ, EX2, and the translator drops FMZ, so pow(0, 0) is
# NaN instead of 1; a NaN in the sky-ambient SH block then blacks fog and ambient for good. Scans the shader cache
# (in parallel) for that pattern and rewrites those multiplies as (a == 0 || b == 0) ? 0 : a * b. Runs after
# `shaders`; files already fixed have a .orig beside them and are rewritten from it (idempotent).
fmzpow:
    cd "{{src}}" && {{dev}} bash -c 'find build/{{ver}}/shader-cache -name "*.spv" -print0 | xargs -0 -P"$(nproc)" -n 500 python3 "{{flake}}/tools/fmz-pow-scan.py" | cut -d" " -f1 | xargs -r -n 200 python3 "{{flake}}/tools/fmz-pow.py"'

# OBSOLETE (root cause fixed by private patch 0004 / build f33ed65; kept only for `nanguard restore`): NaN guard on the volumetric fog light-injection shader (its NaN blacks the picture; NOTES-fog-nan.md).
# Runs after `shaders`; `just nanguard restore` puts the original SPIR-V back.
fog_spv := "1201517696dd2e1d9ad6735249bb9160bf2fd71a5e45b176400585a8371a5083"
nanguard *mode:
    cd "{{src}}" && {{dev}} python3 "{{flake}}/tools/nan-guard.py" build/{{ver}}/shader-cache --sha256 {{fog_spv}} {{ if mode == "restore" { "--restore" } else { "" } }}

# Play
run *args:
    cd "{{src}}" && {{dev}} env {{radv}} {{wrapper}} build/{{ver}}/nx2navi {{args}}

# Play under gdb, everything logged to NX2navi/build/{{ver}}/logs/run-<time>.log (a fatal error comes with the host
# backtrace of every fault); Tally watches that folder from the container
debug *args:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{src}}"
    mkdir -p "build/{{ver}}/logs"
    log="build/{{ver}}/logs/run-$(date +%Y%m%d-%H%M%S).log"
    echo "log: $log"
    mkdir -p "{{jobs_dir}}"; job="{{jobs_dir}}/nx2navi.json"
    printf '{"name":"nx2navi","log":"%s","since":%s,"progress":{"regex":"frame (?P<done>[0-9]+):"},"pid":%s}\n' "$PWD/$log" "$(date +%s)" "$$" > "$job"
    trap 'rm -f "$job"' EXIT
    # -nx: the user's ~/.gdbinit (a dashboard) would draw terminal panes into the log; no stdin: nothing to prompt
    {{dev}} env TERM=dumb {{radv}} {{wrapper}} nix shell nixpkgs#gdb -c gdb -nx -batch -q -x "{{flake}}/tools/crash.gdb" --args "build/{{ver}}/nx2navi" {{args}} < /dev/null 2>&1 | tee "$log" | grep -a -v -E "no such proc|preparation progress|PushComputeConstants"

# `just play` on the combined build with the unproven switches of UNCERTAIN.md that passed the lab: the flicker fix,
# the memory switches and the faster shadow copies; live shader reload and shot.req / dump.req are on, so Tally can
# capture frames and swap shaders while Cal sits in a scene. Each can still be overridden from the environment.
# The burst build (NX2NAVI_EXE=burst NX2NAVI_MARK_RING=120 NX2NAVI_MARK_BURST=120) froze the game at its first mark
# on 2026-11-10: not for play until that is fixed.
# NX2NAVI_MARK_RING / NX2NAVI_MARK_BURST (patch 0049) and any other NX2NAVI_ knob pass through from the environment
# Default binary: nx2navi.play3 (patches through 0065; play2 = through 0064): live debugging without a restart, watch.req / peek.req / buf.req /
# pick.req (NX2NAVI_WATCH_REQ=1), F5 pick, Shift+F5 crosshair, F6 shot, F12 dump, Shift+F6 broken, Shift+F12 fixed.
try *args:
    NX2NAVI_EXE="${NX2NAVI_EXE:-play3}" NX2NAVI_WATCH_REQ="${NX2NAVI_WATCH_REQ:-1}" \
    NX2NAVI_TEX_RELEASED_YIELD="${NX2NAVI_TEX_RELEASED_YIELD:-85}" \
    NX2NAVI_ALIAS_EXTRA_MIB="${NX2NAVI_ALIAS_EXTRA_MIB:-512}" NX2NAVI_AO_ORDER="${NX2NAVI_AO_ORDER:-1}" \
    NX2NAVI_SHADOW_NT="${NX2NAVI_SHADOW_NT:-1}" \
    NX2NAVI_SHADER_RELOAD="${NX2NAVI_SHADER_RELOAD:-1}" NX2NAVI_DUMP_REQ="${NX2NAVI_DUMP_REQ:-1}" \
    {{just_executable()}} -f "{{justfile()}}" play {{args}}

# `just try` on nx2navi.play5 (0001-0067, mesh draws in dumps) with the translator fix 0064 (#164, signed I2F): its own translator, shader cache and pipeline cache copy
# under build/v111 (*-i2f), so the live caches stay as they are. Every shader is translated again on first use.
try-i2f *args:
    NX2NAVI_EXE="${NX2NAVI_EXE:-play5}" NX2NAVI_XLATE="${NX2NAVI_XLATE:-{{src}}/build/{{ver}}/xlate-i2f/nx2navi_xlate}" \
    NX2NAVI_SHADER_CACHE="${NX2NAVI_SHADER_CACHE:-{{src}}/build/{{ver}}/shader-cache-i2f}" \
    NX2NAVI_PIPELINE_CACHE="${NX2NAVI_PIPELINE_CACHE:-{{src}}/build/{{ver}}/pipeline-cache-i2f.bin}" \
    {{just_executable()}} -f "{{justfile()}}" try {{args}}

# Text mod (#170), built into NX2navi/build/{{ver}}/mods-text/text from the game's own text: Link renamed to NAME
# (whole words, tags untouched; an empty NAME keeps the last one, saved in mods-text/name) plus every change in
# build/{{ver}}/items.toml (`just items` makes it). Python 3.14 from nixpkgs, stdlib only: host or container.
text NAME="":
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{src}}"
    py="nix shell nixpkgs#python314 -c python3 -I"
    out="build/{{ver}}/mods-text" edits="build/{{ver}}/msg-edit-text"
    mkdir -p "$out"
    name="{{NAME}}"; [ -n "$name" ] || name=$(cat "$out/name" 2>/dev/null || true)
    rm -rf "$edits" && mkdir -p "$edits/USen"
    if [ -n "$name" ] && [ "$name" != Link ]; then $py ../tools/msgmod.py rename --old Link --new "$name" --edits "$edits"; fi
    printf '%s\n' "${name:-Link}" > "$out/name"
    if [ -f "build/{{ver}}/items.toml" ]; then $py ../tools/itemtext.py apply --export "build/{{ver}}/msg/USen" --items "build/{{ver}}/items.toml" --edits "$edits/USen"; fi
    $py ../tools/msgmod.py build --mod text --mods-dir "$out" --edits "$edits"
    $py ../tools/msgmod.py check --mod text --mods-dir "$out" --edits "$edits"

# Make NX2navi/build/{{ver}}/items.toml: every item's name and description on the Items screen, to edit. Then
# `just try-name` (or `just text`) builds them into the text mod.
items:
    cd "{{src}}" && nix shell nixpkgs#python314 -c python3 -I ../tools/itemtext.py init --export "build/{{ver}}/msg/USen" --out "build/{{ver}}/items.toml"

# try-vram with the text mod: rebuilds it first (Link renamed to NAME, or the last name; items.toml applied).
try-name NAME="" *args:
    {{just_executable()}} -f "{{justfile()}}" text "{{NAME}}"
    NX2NAVI_MODS_DIR="${NX2NAVI_MODS_DIR:-{{src}}/build/{{ver}}/mods-text}" {{just_executable()}} -f "{{justfile()}}" try-vram {{args}}

# try-i2f on play11 with the VRAM hold settings (#160): render-target reuse on (off: 30 fps in Hyrule from churn;
# on is suspected of a lighting flicker, being made safe), trim at 85%, released cap
# 1536 MiB with LRU, live textures idle 15 s may drop. Lab 46k frames: card 84-94% vs 91-99%, 0 vs 51 trims at 95%,
# worst frame 27 vs 98 ms, no fps cost (66.6 vs 66.2, n=5). STALE_LIVE=1 is the #149/#169 terrain fix (lab: 3974
# tiles recovered, 0 unresolved). MARK_CHORD=off gives L3+R3 back to the game (mark with yakin's ...+Start). Any variable can be overridden from the environment.
# RT_RECYCLE is off (2026-11-11): on play11 it gave back render targets the game took back with their content lost,
# environment lighting flickered with camera angle and time of day (play-20261111-115322).
# #174 texel fetch clamp: nx2navi.tld with TLD_CLAMP=1 and TEX_DESC_STRICT=1, its own translator (xlate-tld), shader
# cache and pipeline cache copy (*-tld). Live dumps (dump.req) land in build/v111/dump as with every try.
# Runs through try-name, so the text mod and the try-vram settings apply as on Cal's usual line.
try-tld *args:
    NX2NAVI_EXE="${NX2NAVI_EXE:-tld}" NX2NAVI_TLD_CLAMP="${NX2NAVI_TLD_CLAMP:-1}" \
    NX2NAVI_TEX_DESC_STRICT="${NX2NAVI_TEX_DESC_STRICT:-1}" \
    NX2NAVI_XLATE="${NX2NAVI_XLATE:-{{src}}/build/{{ver}}/xlate-tld/nx2navi_xlate}" \
    NX2NAVI_SHADER_CACHE="${NX2NAVI_SHADER_CACHE:-{{src}}/build/{{ver}}/shader-cache-tld}" \
    NX2NAVI_PIPELINE_CACHE="${NX2NAVI_PIPELINE_CACHE:-{{src}}/build/{{ver}}/pipeline-cache-tld.bin}" \
    {{just_executable()}} -f "{{justfile()}}" try-name "" {{args}}

try-vram *args:
    NX2NAVI_EXE="${NX2NAVI_EXE:-play11}" NX2NAVI_TEX_RT_RECYCLE="${NX2NAVI_TEX_RT_RECYCLE:-1}" \
    NX2NAVI_TEX_RT_TRIM="${NX2NAVI_TEX_RT_TRIM:-85}" NX2NAVI_TEX_RT_TRIM_PER_MIN="${NX2NAVI_TEX_RT_TRIM_PER_MIN:-0}" \
    NX2NAVI_TEX_RELEASED_MIB="${NX2NAVI_TEX_RELEASED_MIB:-1536}" NX2NAVI_TEX_RELEASED_LRU="${NX2NAVI_TEX_RELEASED_LRU:-1}" \
    NX2NAVI_TEX_LIVE_IDLE="${NX2NAVI_TEX_LIVE_IDLE:-900}" NX2NAVI_TEX_STALE_LIVE="${NX2NAVI_TEX_STALE_LIVE:-1}" \
    NX2NAVI_MARK_CHORD="${NX2NAVI_MARK_CHORD:-off}" \
    {{just_executable()}} -f "{{justfile()}}" try-i2f {{args}}

# Play casually with everything Tally needs if something goes wrong, at no measurable cost: no debugger, the log
# teed to NX2navi/build/{{ver}}/logs/play-<time>.log, every input recorded beside it (replayable with `just replay`),
# core dumps on, and the run registered as a job so the error watch and the screensaver see it.
# Defaults (#132): async replay and the Vulkan recorder thread on, about 5% more fps on the haze scene; set either to 0 to override.
play *args:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{src}}"
    mkdir -p "build/{{ver}}/logs"
    # live dumps (dump.req) beside the logs, not in the checkout's root (the runtime's default "dump" is cwd-relative)
    export NX2NAVI_DUMP_DIR="${NX2NAVI_DUMP_DIR:-$PWD/build/{{ver}}/dump}"
    ts=$(date +%Y%m%d-%H%M%S)
    log="build/{{ver}}/logs/play-$ts.log"
    echo "log: $log"
    # recording bundle: the save this recording starts from, so lab-run replays it exactly (keep the newest 40)
    snap="build/{{ver}}/logs/profile-$ts"; mkdir -p "$snap"
    for d in save save-tx save-backup; do [ -d "build/{{ver}}/profile/$d" ] && cp -a "build/{{ver}}/profile/$d" "$snap/"; done
    ls -d build/{{ver}}/logs/profile-*/ | sort | head -n -40 | xargs -r rm -rf
    mkdir -p "{{jobs_dir}}"; job="{{jobs_dir}}/nx2navi.json"
    printf '{"name":"nx2navi","log":"%s","since":%s,"progress":{"regex":"frame (?P<done>[0-9]+):"},"pid":%s}\n' "$PWD/$log" "$(date +%s)" "$$" > "$job"
    trap 'rm -f "$job"' EXIT
    ulimit -c unlimited || true
    # CPU pinning (UNCERTAIN.md): on a CPU with several L3 cache domains (a Ryzen 9's two CCDs) keep the game
    # on the first one. NX2NAVI_CPUS=off leaves it unpinned, NX2NAVI_CPUS=<list> pins to that taskset list.
    cpus=${NX2NAVI_CPUS:-auto}
    if [ "$cpus" = auto ]; then
        cpus=off
        if [ "$(cat /sys/devices/system/cpu/cpu*/cache/index3/shared_cpu_list 2>/dev/null | sort -u | wc -l)" -gt 1 ]; then
            cpus=$(cat /sys/devices/system/cpu/cpu0/cache/index3/shared_cpu_list)
        fi
    fi
    if [ "$cpus" != off ] && command -v taskset >/dev/null; then
        taskset -pc "$cpus" $$ >/dev/null && echo "cpus: pinned to $cpus (NX2NAVI_CPUS=off to disable)"
    fi
    {{dev}} env {{radv}} NX2NAVI_HDR=${NX2NAVI_HDR:-native} NX2NAVI_REPLAY_ASYNC=${NX2NAVI_REPLAY_ASYNC:-1} NX2NAVI_VK_RECORDER=${NX2NAVI_VK_RECORDER:-1} NX2NAVI_TEX_RELEASED_MIB=${NX2NAVI_TEX_RELEASED_MIB:-3072} NX2NAVI_GPU_WAIT=${NX2NAVI_GPU_WAIT:-0} NX2NAVI_INPUT_RECORD="build/{{ver}}/logs/input-$ts.txt" {{wrapper}} "build/{{ver}}/nx2navi${NX2NAVI_EXE:+.$NX2NAVI_EXE}" {{args}} 2>&1 | tee "$log" | grep -a -v -E "no such proc|preparation progress|PushComputeConstants"

# Play under gdb like `debug`, and record every input to NX2navi/build/{{ver}}/logs/input-<time>.txt: the recording
# replays with `just replay <file>` (Tally runs it from the container to reproduce a crash)
record *args:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{src}}"
    mkdir -p "build/{{ver}}/logs"
    t=$(date +%Y%m%d-%H%M%S); log="build/{{ver}}/logs/run-$t.log"; rec="build/{{ver}}/logs/input-$t.txt"
    echo "log: $log"; echo "recording: $rec"
    mkdir -p "{{jobs_dir}}"; job="{{jobs_dir}}/nx2navi.json"
    printf '{"name":"nx2navi","log":"%s","since":%s,"progress":{"regex":"frame (?P<done>[0-9]+):"},"pid":%s}\n' "$PWD/$log" "$(date +%s)" "$$" > "$job"
    trap 'rm -f "$job"' EXIT
    {{dev}} env TERM=dumb {{radv}} NX2NAVI_INPUT_RECORD="$rec" {{wrapper}} nix shell nixpkgs#gdb -c gdb -nx -batch -q -x "{{flake}}/tools/crash.gdb" --args "build/{{ver}}/nx2navi" {{args}} < /dev/null 2>&1 | tee "$log" | grep -a -v -E "no such proc|preparation progress|PushComputeConstants"

# Replay a recording under gdb (NX2NAVI_INPUT_SCRIPT), log as `debug`; extra env after the file: just replay in.txt NX2NAVI_X=1
replay file *env:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{src}}"
    mkdir -p "build/{{ver}}/logs"
    log="build/{{ver}}/logs/run-$(date +%Y%m%d-%H%M%S)-replay.log"
    echo "log: $log"
    mkdir -p "{{jobs_dir}}"; job="{{jobs_dir}}/nx2navi.json"
    printf '{"name":"nx2navi","log":"%s","since":%s,"progress":{"regex":"frame (?P<done>[0-9]+):"},"pid":%s}\n' "$PWD/$log" "$(date +%s)" "$$" > "$job"
    trap 'rm -f "$job"' EXIT
    {{dev}} env TERM=dumb {{radv}} NX2NAVI_INPUT_SCRIPT="{{file}}" {{env}} {{wrapper}} nix shell nixpkgs#gdb -c gdb -nx -batch -q -x "{{flake}}/tools/crash.gdb" --args "build/{{ver}}/nx2navi" < /dev/null 2>&1 | tee "$log" | grep -a -v -E "no such proc|preparation progress|PushComputeConstants"

# Selftest and Vulkan check without game files on the GPU
selftest:
    cd "{{src}}" && {{dev}} env {{radv}} {{wrapper}} build/{{ver}}/nx2navi --selftest

# Differential test of the SM86 lowering (patch 0085, tests/xdiff): every instruction form in the shader cache's
# stored inputs, lowered by the translator and checked against an SM86 reference on random inputs; reads the cache
# only, CPU only (niced, lab cores), report in build/xdiff/report.txt. E.g. just xdiff --shaders 2000 --opcode I2F,IMAD
xdiff *args:
    cd "{{src}}" && nice -n 19 taskset -c 12-15,28-31 python3 -I tests/xdiff/xdiff.py --cache build/{{ver}}/shader-cache --xlate build/xlate/nx2navi_xlate --jobs 8 {{args}}

# Pull upstream and rebuild what changed
update: && xlate game shaders
    git -C ~/claude/.bare/NX2navi.git fetch
    git -C "{{src}}" merge --ff-only origin/main

# Open the shell itself
shell:
    cd "{{src}}" && NX2NAVI_NVIDIA={{ if gpu == "nvidia" { "1" } else { "0" } }} nix develop {{impure}} "{{flake}}"

# The build kit as a Flatpak bundle (flatpak/README.md): toolchain, patched sources, launcher; no game files, no
# game binary. For Cal's own devices only: never publish it. Writes flatpak/nx2navi-kit.flatpak.
flatpak:
    cd "{{flake}}/flatpak" && nix shell nixpkgs#flatpak nixpkgs#flatpak-builder -c bash -c '\
        flatpak --user remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo && \
        flatpak-builder --user --install-deps-from=flathub --force-clean --ccache --repo=.repo .build io.github.dsktd.NX2navi.yml && \
        flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo .repo nx2navi-kit.flatpak io.github.dsktd.NX2navi'

# Install the bundle for this user (the runtime comes from Flathub)
flatpak-install:
    nix shell nixpkgs#flatpak -c flatpak install --user -y "{{flake}}/flatpak/nx2navi-kit.flatpak"

# Set up or update a Steam Deck over SSH (flatpak/deck-setup): kit bundle, prebuilt game or the .nup, Steam shortcut.
#   just host=steamdeck deck            just host=steamdeck nup=/path/game.nup deck
deck:
    test -n "{{host}}" || { echo "set NX2NAVI_DECK (or host=...) to the Deck's hostname or IP"; exit 1; }
    "{{flake}}/flatpak/deck-setup" "{{host}}" {{ if nup != "" { "nup " + quote(nup) } else { "" } }}

# Replay one scenario of scenarios/ through tools/lab-run and print pass/fail per check (scenarios/README.md);
# NX2NAVI_EXE=<variant> judges build/v111/nx2navi.<variant>; --dry prints the plan only
scenario *args:
    python3 -I "{{flake}}/tools/scenario" run {{args}}

# Every regression-grade scenario (or the named ones): one table, JSON in .lab/regress/, non-zero exit on a failure
regress *args:
    python3 -I "{{flake}}/tools/scenario" regress {{args}}

# A new starting-point scenario from a `just play` session: just scenario-add <name> from 20261109-234907 [frame]
scenario-add name from session frame="999999":
    python3 -I "{{flake}}/tools/scenario" add {{name}} {{from}} {{session}} {{frame}}

# Pin the desktop (Niri, audio, bar) to the system's cores 8-11,24-27 now, away from the game (0-7,16-23) and Tally
# (12-15,28-31). Runtime only: a restart of those processes or a reboot undoes it. CPUS=<list> picks other cores.
pin-desktop CPUS="8-11,24-27":
    #!/usr/bin/env bash
    for name in niri pipewire pipewire-pulse wireplumber waybar Xwayland xwayland-satell mako; do  # comm names are cut at 15 characters
        for pid in $(pgrep -x "$name"); do taskset -apc "{{CPUS}}" "$pid" >/dev/null && echo "$name $pid -> {{CPUS}}"; done
    done

# One entry point for test setups: `just run <name>` runs runs/<name>.sh (each script holds that test's settings,
# with a header saying what it tests, its tracker item and when to delete it); no name runs the usual play setup.
run NAME="" *args:
    #!/usr/bin/env sh
    if [ -z "{{NAME}}" ]; then exec {{just_executable()}} -f "{{justfile()}}" try-name "" {{args}}; fi
    exec sh "{{justfile_directory()}}/runs/{{NAME}}.sh" {{args}}
