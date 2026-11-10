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
# the memory switches and the faster shadow copies. Each can still be overridden from the environment.
try *args:
    NX2NAVI_EXE="${NX2NAVI_EXE:-next}" NX2NAVI_TEX_RELEASED_YIELD="${NX2NAVI_TEX_RELEASED_YIELD:-85}" \
    NX2NAVI_ALIAS_EXTRA_MIB="${NX2NAVI_ALIAS_EXTRA_MIB:-512}" NX2NAVI_AO_ORDER="${NX2NAVI_AO_ORDER:-1}" \
    NX2NAVI_SHADOW_NT="${NX2NAVI_SHADOW_NT:-1}" {{just_executable()}} -f "{{justfile()}}" play {{args}}

# Play casually with everything Tally needs if something goes wrong, at no measurable cost: no debugger, the log
# teed to NX2navi/build/{{ver}}/logs/play-<time>.log, every input recorded beside it (replayable with `just replay`),
# core dumps on, and the run registered as a job so the error watch and the screensaver see it.
# Defaults (#132): async replay and the Vulkan recorder thread on, about 5% more fps on the haze scene; set either to 0 to override.
play *args:
    #!/usr/bin/env bash
    set -euo pipefail
    cd "{{src}}"
    mkdir -p "build/{{ver}}/logs"
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
