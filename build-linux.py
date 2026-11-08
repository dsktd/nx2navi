#!/usr/bin/env python3
"""Build Ocarina of Time 1.1.1 (NX2navi) for Linux, from a .nup unpacked by the kit.

The repository has two build paths and neither does this alone: tools/make_game.py (the build kit) knows the 1.1.1
game, lifts it with two bring-up fixes and writes the glue (modules.c) with the Switch 2 constants, but compiles with
MSYS2 on Windows only; tools/build_game.py builds on Linux with SDL3, but its glue carries the Switch 1 constants of
the other game versions. This driver runs the kit's own code for the lift and the glue, then compiles and links with
the flags build_game.py documents for Linux, through Ninja. Nothing in the checkout is modified.

    build-linux.py --src <checkout> [--extracted build/extracted/v111] [--out build/v111] [--cpu v3|v2] [--jobs N]

Steps (each incremental), after make_game.py's exefs and romfs steps have filled <extracted>:
  lift      make_game.step_lift: the kit lifts <extracted>/exefs into <extracted>/build-cache/lift with its fixes
  glue      romfs_index.py -> <out>/romfs-index.bin and romfs_config.h; make_game.modules_c -> <out>/gen/modules.c
  compile   Ninja: the lifted C at -O1, the runtime (SDL3 and platform/linux.c) at -O2, linked into <out>/nx2navi
  copy      the translator (build/xlate/nx2navi_xlate and its .id, from tools/build_xlate.py) beside the game

Environment: NX2NAVI_VMA_INCLUDE names the directory holding vk_mem_alloc.h (the flake sets it).
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

GEN_FLAGS = ['-O1', '-fno-strict-aliasing', '-Wno-return-type', '-Wno-unused-label', '-fvisibility=hidden']
RT_FLAGS = ['-O2', '-g', '-Wall', '-fno-strict-aliasing']
LINK_FLAGS = ['-fuse-ld=lld', '-no-pie', '-Wl,-z,noexecstack', '-Wl,-rpath,$$ORIGIN']
# build_game.py's Linux libraries, plus dav1d (runtime/ov_movie2.c, the Switch 2 movies) and libatomic as the kit links
LINK_LIBS = ['-lvulkan', '-lSDL3', '-lopus', '-lvpx', '-ldav1d', '-lzstd', '-latomic', '-l:libstdc++.a', '-lm',
             '-lpthread', '-ldl']
MODULES = ('main', 'sdk', 'subsdk0')
RUNTIME_PATTERNS = ('*.c', '*.cpp', 'platform/*.c', 'ui/*.cpp', 'third_party/imgui/*.cpp',
                    'third_party/imgui/backends/*.cpp')


def other_os(name):
    stem = name.rsplit('.', 1)[0]
    return stem.endswith('_win') or name in ('win32.c', 'nx2navi.rc')


def runtime_sources(runtime):
    return sorted(p for pat in RUNTIME_PATTERNS for p in runtime.glob(pat) if not other_os(p.name))


def npath(p):
    return str(p).replace('$', '$$').replace(' ', '$ ').replace(':', '$:')


def run(cmd, **kw):
    print('+', ' '.join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], **kw)
    if r.returncode:
        sys.exit(f'build-linux: {Path(str(cmd[0])).name} failed ({r.returncode})')


def kit(py, src, code, *args):
    """Run code inside the kit (tools/make_game.py imported as k), with the kit's interpreter."""
    pre = 'import sys; sys.path.insert(0, sys.argv[1]); import make_game as k; from pathlib import Path; '
    run([py, '-I', '-c', pre + code, src / 'tools', *args], cwd=src)


def step_lift(src, py, extracted):
    for name in ('main', 'main.npdm', 'sdk', 'subsdk0', 'rtld'):
        if not (extracted / 'exefs' / name).is_file():
            sys.exit(f'build-linux: {extracted / "exefs" / name} missing: run make_game.py --until romfs first (just extract)')
    kit(py, src, 'k.step_lift(Path(sys.argv[2]), Path(sys.argv[3]))', extracted, extracted / 'build-cache')


def step_glue(src, py, extracted, out, lift):
    run([py, '-I', src / 'tools' / 'romfs_index.py', '--romfs', extracted / 'romfs', '--out', out], cwd=src)
    gen = out / 'gen'
    gen.mkdir(parents=True, exist_ok=True)
    # the kit's own glue writer, so the constants stay its
    kit(py, src, 'k.modules_c(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))', lift, extracted, gen)
    # shim.c defines the SDL menu hook for the Win32 window; this build has the SDL window, which defines it itself
    (gen / 'shim.c').unlink(missing_ok=True)
    return gen


def write_ninja(src, out, lift, gen, cpu):
    runtime = src / 'runtime'
    march = f'-march=x86-64-{cpu}'
    vma = os.environ.get('NX2NAVI_VMA_INCLUDE') or '/usr/include'
    if not (Path(vma) / 'vk_mem_alloc.h').is_file():
        sys.exit(f'build-linux: no vk_mem_alloc.h in {vma} (set NX2NAVI_VMA_INCLUDE)')
    inc = f'-I {npath(runtime)} -I {npath(lift)} -I {npath(gen)}'
    rt_inc = f'{inc} -I {npath(out)} -I {npath(vma)} -I {npath(runtime / "third_party" / "imgui")}'
    lines = [
        '# Written by build-linux.py; do not edit.',
        'ninja_required_version = 1.10',
        f'builddir = {npath(out)}',
        'cc = clang',
        f'genflags = {" ".join(GEN_FLAGS)} {march} {inc}',
        f'rtflags = {" ".join(RT_FLAGS)} {march} -DRT_CPU_LEVEL={3 if cpu == "v3" else 2} {rt_inc}',
        f'ldflags = {" ".join(LINK_FLAGS)} -Wl,-Map={npath(out / "nx2navi.map")}',
        f'libs = {" ".join(LINK_LIBS)}',
        '',
        'rule cc_gen', '  command = $cc $genflags -MD -MF $out.d -c $in -o $out', '  deps = gcc', '  depfile = $out.d',
        '  description = CC $in', '',
        'rule cc_rt', '  command = $cc $rtflags -MD -MF $out.d -c $in -o $out', '  deps = gcc', '  depfile = $out.d',
        '  description = CC $in', '',
        'rule link', '  command = $cc $ldflags @$out.rsp $libs -o $out', '  rspfile = $out.rsp',
        '  rspfile_content = $in_newline', '  description = LINK $out', '',
    ]
    objs = []
    for mod in MODULES:
        for f in sorted((lift / mod).glob('*.c')):
            o = out / 'obj' / mod / (f.stem + '.o')
            lines.append(f'build {npath(o)}: cc_gen {npath(f)}')
            objs.append(o)
    sources = runtime_sources(runtime) + [gen / 'modules.c']
    for s in sources:
        rel = s.relative_to(runtime) if s.is_relative_to(runtime) else Path(s.name)
        o = out / 'obj' / 'runtime' / rel.with_suffix('.o')
        lines.append(f'build {npath(o)}: cc_rt {npath(s)}')
        objs.append(o)
    exe = out / 'nx2navi'
    lines += [f'build {npath(exe)}: link ' + ' '.join(npath(o) for o in objs), f'default {npath(exe)}', '']
    out.mkdir(parents=True, exist_ok=True)
    (out / 'build.ninja').write_text('\n'.join(lines), encoding='utf-8')


def step_copy(src, out):
    xlate = src / 'build' / 'xlate'
    for name in ('nx2navi_xlate', 'nx2navi_xlate.id'):
        f = xlate / name
        if not f.is_file():
            print(f'build-linux: {f} missing: run tools/build_xlate.py (just xlate) before the shaders', file=sys.stderr)
            return
        shutil.copy2(f, out / name)
    (out / 'profile').mkdir(exist_ok=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--src', type=Path, required=True, help='the NX2navi checkout')
    ap.add_argument('--extracted', type=Path, help='the kit output: exefs/, romfs/ (default <src>/build/extracted/v111)')
    ap.add_argument('--out', type=Path, help='the game folder (default <src>/build/v111)')
    ap.add_argument('--cpu', choices=('v2', 'v3'), default='v3')
    ap.add_argument('--jobs', type=int, default=os.cpu_count() or 4)
    ap.add_argument('--python', type=Path, help='the kit interpreter (default <src>/.venv/bin/python)')
    a = ap.parse_args()
    src = a.src.resolve()
    extracted = (a.extracted or src / 'build' / 'extracted' / 'v111').resolve()
    out = (a.out or src / 'build' / 'v111').resolve()
    py = (a.python or src / '.venv' / 'bin' / 'python').absolute()   # not resolve(): a venv's python is a symlink
    lift = extracted / 'build-cache' / 'lift'
    step_lift(src, py, extracted)
    gen = step_glue(src, py, extracted, out, lift)
    write_ninja(src, out, lift, gen, a.cpu)
    run(['ninja', '-C', out, f'-j{a.jobs}'])
    step_copy(src, out)
    print(f'\nbuild-linux: {out / "nx2navi"} ({(out / "nx2navi").stat().st_size / 1e6:.0f} MB)')


if __name__ == '__main__':
    main()
