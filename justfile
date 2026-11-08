# NX2navi on the desktop, every step inside the flake's shell. Settings by environment or on the command line:
#   just src=~/claude/nx2navi/NX2navi ver=v111 build   (the defaults; src is a worktree of ~/claude/.bare/NX2navi.git)
#   NX2NAVI_GPU=nvidia just run                 (NVIDIA host driver through nixGL; Mesa is the default)
#   NX2NAVI_NUP=/path/game.nup just extract     (the dump as a .nup: no keys needed; or just nup=/path/game.nup extract)

set shell := ["bash", "-euo", "pipefail", "-c"]

src := env("NX2NAVI_SRC", justfile_directory() / "NX2navi")
ver := env("NX2NAVI_VER", "v111")
gpu := env("NX2NAVI_GPU", "mesa")
nup := env("NX2NAVI_NUP", "")
# the [work] dir of config.local.toml (where build_game.py looks for extracted/<ver>)
work := env("NX2NAVI_WORK", "build")
# make_game.py insists on an MSYS2 folder before it starts, although the extraction never uses it: an empty stand-in
msys := justfile_directory() / ".msys-stub"
flake := justfile_directory()
impure := if gpu == "nvidia" { "--impure" } else { "" }
wrapper := if gpu == "nvidia" { "nixVulkanNvidia" } else { "nixVulkanIntel" }
# RADV (Mesa 26.2.6) segfaults in its graphics pipeline library path while this game builds pipelines
# (libvulkan_radeon.so+0x19be92, found 2026-11-08 on an RX 6900 XT); without it the runtime builds whole pipelines
radv := "RADV_DEBUG=nogpl"
dev := "NX2NAVI_NVIDIA=" + (if gpu == "nvidia" { "1" } else { "0" }) + " nix develop " + impure + " " + flake + " --command"
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
    cd "{{src}}" && {{dev}} {{py}} tools/build_xlate.py

# Lift (the kit, with its bring-up fixes), glue, compile and link build/{{ver}}/nx2navi (a CPU without AVX2: just game v2)
game cpu="v3":
    cd "{{src}}" && {{dev}} python3 -I "{{flake}}/build-linux.py" --src "{{src}}" --extracted "{{work}}/extracted/{{ver}}" --out "build/{{ver}}" --cpu {{cpu}}

# Prepare every shader of the game files and warm the GPU driver's cache (opens a window: run from the desktop session)
shaders:
    cd "{{src}}" && {{dev}} env {{radv}} {{wrapper}} {{py314}} tools/prepare_shaders.py build/{{ver}} --romfs "{{work}}/extracted/{{ver}}/romfs" --exefs "{{work}}/extracted/{{ver}}/exefs" --no-list

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
    {{dev}} env {{radv}} {{wrapper}} nix shell nixpkgs#gdb -c gdb -batch -q -x "{{flake}}/tools/crash.gdb" --args "build/{{ver}}/nx2navi" {{args}} 2>&1 | tee "$log" | grep -v -E "no such proc|preparation progress|PushComputeConstants"

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
