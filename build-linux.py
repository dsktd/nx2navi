#!/usr/bin/env python3
"""Build Ocarina of Time 1.1.1 (NX2navi) for Linux, from a .nup unpacked by the kit.

The repository has two build paths and neither does this alone: tools/make_game.py (the build kit) knows the 1.1.1
game, lifts it with two bring-up fixes and writes the glue (modules.c) with the Switch 2 constants, but compiles with
MSYS2 on Windows only; tools/build_game.py builds on Linux with SDL3, but its glue carries the Switch 1 constants of
the other game versions. This driver runs the kit's own code for the lift and the glue, then compiles and links with
the flags build_game.py documents for Linux, through Ninja. Nothing in the checkout is modified.

    build-linux.py --src <checkout> [--extracted build/extracted/v111] [--out build/v111] [--cpu v3|v2] [--jobs N]
                   [--exe nx2navi] [--tracy] [--rt-obj NAME] [--guest-opt 1|2|3] [--guest-flags '...']
                   [--guest-obj NAME] [--link-flags '...'] [--no-ccache]

Steps (each incremental), after make_game.py's exefs and romfs steps have filled <extracted>:
  lift      make_game.step_lift: the kit lifts <extracted>/exefs into <extracted>/build-cache/lift with its fixes
  glue      romfs_index.py -> <out>/romfs-index.bin and romfs_config.h; make_game.modules_c -> <out>/gen/modules.c
  compile   Ninja: the lifted C at -O1 (--guest-opt), the runtime (SDL3 and platform/linux.c) at -O2, linked into <out>/nx2navi
  copy      the translator (build/xlate/nx2navi_xlate and its .id, from tools/build_xlate.py) beside the game

Environment: NX2NAVI_VMA_INCLUDE names the directory holding vk_mem_alloc.h (the flake sets it).
--exe names the binary in <out> (its ninja file is build.<exe>.ninja); --tracy compiles the runtime with the Tracy
client (-DTRACY_ENABLE, runtime/rt_tracy.h zones) and links libTracyClient from NX2NAVI_TRACY_PREFIX (the flake
sets it to nixpkgs tracy); its runtime objects go to obj/runtime-tracy. README "Profiling with Tracy".
--guest-opt is the optimisation level of the lifted game code (default 1, upstream's choice for its build time);
--guest-flags appends to its compile line (later flags win, so '-march=znver3' replaces the --cpu level for the
game code only; the Nix clang wrapper drops -march=native, name the CPU) and --link-flags to the link line (PGO:
-fprofile-generate on both, then --guest-flags '-fprofile-use=<file.profdata>'). A level other than 1 or any
--guest-flags puts the game objects under obj/guest-<tag>/, the tag derived from the level and the flags (O2,
O2-znver3; --guest-obj names it instead), and leaves obj/{main,sdk,subsdk0} alone: every variant keeps its objects,
switching between them compiles nothing. NOTES-perf-2026-11-09.md "Guest optimisation level".
Compiler cache: with ccache on PATH (the flake has it) every compile goes through it, cache in .ccache/ beside this
script (CCACHE_DIR overrides; 40 GB), so a translation unit is compiled once per set of flags, in any source tree
laid out the same way (paths below the checkout are hashed relative). ccache stands in as `clang` through a PATH
entry, so the ninja command lines do not change and nothing already built is rebuilt. --no-ccache turns it off.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# the level (-O1 unless --guest-opt says otherwise) goes in front in write_ninja
GEN_FLAGS = ['-fno-strict-aliasing', '-Wno-return-type', '-Wno-unused-label', '-fvisibility=hidden']
# -fdeclspec: third_party/ffx_api/ffx_api.h declares its entry points __declspec(dllexport) on every OS
RT_FLAGS = ['-O2', '-g', '-Wall', '-fno-strict-aliasing', '-fdeclspec']
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
    # one BLAS thread per lift worker: numpy's default (a thread per core in each of the workers, 32 x 32 here) ran
    # into the container's limit of 2048 tasks and the lift hung on "pthread_create failed" (2026-11-09)
    env = {'OPENBLAS_NUM_THREADS': '1', **os.environ}
    run([py, '-I', '-c', pre + code, src / 'tools', *args], cwd=src, env=env)


def step_lift(src, py, extracted):
    for name in ('main', 'main.npdm', 'sdk', 'subsdk0', 'rtld'):
        if not (extracted / 'exefs' / name).is_file():
            sys.exit(f'build-linux: {extracted / "exefs" / name} missing: run make_game.py --until romfs first (just extract)')
    kit(py, src, 'k.step_lift(Path(sys.argv[2]), Path(sys.argv[3]))', extracted, extracted / 'build-cache')


def step_glue(src, py, extracted, out, lift):
    # no -I: the script imports a sibling (check_content) from its own directory
    run([py, src / 'tools' / 'romfs_index.py', '--romfs', extracted / 'romfs', '--out', out], cwd=src)
    gen = out / 'gen'
    gen.mkdir(parents=True, exist_ok=True)
    # the kit's own glue writer, so the constants stay its
    kit(py, src, 'k.modules_c(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))', lift, extracted, gen)
    # shim.c defines the SDL menu hook for the Win32 window; this build has the SDL window, which defines it itself
    (gen / 'shim.c').unlink(missing_ok=True)
    return gen


HERE = Path(__file__).resolve().parent
# Our Linux additions (runtime-linux/), compiled beside upstream's runtime, and the per-file defines that wire them in
# without editing the checkout: see runtime-linux/frames.c
EXTRA_SOURCES = [HERE / 'runtime-linux' / 'frames.c']
PER_FILE_DEFINES = {
    'platform/linux.c': '-Dplat_frame_capture=plat_frame_capture_stub -Dplat_fiber_new=plat_fiber_new_upstream',
    'guest_setjmp.c': '-Dplat_frame_capture=nx_frame_capture -Dlongjmp=nx_frame_resume',
}
# Per-file flag replacements: the whole rtflags line for that file (see write_ninja)
PER_FILE_FLAGS = {
    # vk_exec_draw.c ran at -O0 to dodge the mesh-stage c0 overrun; patches/0006 fixes it on branch build
}


def guest_tag(opt, flags):
    """The object folder of a guest variant: O2, O2-znver3; flags that make a long name are hashed."""
    words = [re.sub(r'[^A-Za-z0-9.]+', '-', f.lstrip('-').removeprefix('march=')).strip('-') for f in flags.split()]
    tag = '-'.join([f'O{opt}'] + words)
    return tag if len(tag) <= 40 else f'O{opt}-{hashlib.sha256(flags.encode()).hexdigest()[:10]}'


def ccache_env(src):
    """The environment that puts ccache in front of clang, or None without ccache."""
    ccache = shutil.which('ccache')
    if not ccache:
        return None
    cache = Path(os.environ.get('CCACHE_DIR') or HERE / '.ccache')
    shim = cache / 'bin'
    shim.mkdir(parents=True, exist_ok=True)
    for name in ('clang', 'clang++'):
        link = shim / name
        if not link.is_symlink() or os.readlink(link) != ccache:
            link.unlink(missing_ok=True)
            link.symlink_to(ccache)
    return {**os.environ, 'PATH': f'{shim}{os.pathsep}{os.environ["PATH"]}', 'CCACHE_DIR': str(cache),
            'CCACHE_MAXSIZE': os.environ.get('CCACHE_MAXSIZE', '40G'), 'CCACHE_BASEDIR': str(src)}


def write_ninja(src, out, lift, gen, cpu, exe='nx2navi', tracy=None, rt_obj=None, guest_opt='1', guest_flags='',
                guest_obj=None, link_flags=''):
    runtime = src / 'runtime'
    rt_extra = f' -DTRACY_ENABLE -I {npath(tracy / "include" / "tracy")}' if tracy else ''
    ld_extra = f' -L {npath(tracy / "lib")} -Wl,-rpath,{npath(tracy / "lib")}' if tracy else ''
    libs_extra = ' -lTracyClient' if tracy else ''
    rt_obj = rt_obj or ('runtime-tracy' if tracy else 'runtime')
    march = f'-march=x86-64-{cpu}'
    # vk_mem_alloc.h is copied into the build folder: the compile lines then hold no Nix store path, so objects
    # built on one machine (the container) stay valid on another (the host) with the same /home path
    vma_src = Path(os.environ.get('NX2NAVI_VMA_INCLUDE') or '/usr/include') / 'vk_mem_alloc.h'
    if not vma_src.is_file():
        sys.exit(f'build-linux: no {vma_src} (set NX2NAVI_VMA_INCLUDE)')
    vma = out / 'include'
    vma.mkdir(parents=True, exist_ok=True)
    if not (vma / 'vk_mem_alloc.h').is_file() or (vma / 'vk_mem_alloc.h').read_bytes() != vma_src.read_bytes():
        shutil.copyfile(vma_src, vma / 'vk_mem_alloc.h')
    inc = f'-I {npath(runtime)} -I {npath(lift)} -I {npath(gen)}'
    rt_inc = f'{inc} -I {npath(out)} -I {npath(vma)} -I {npath(runtime / "third_party" / "imgui")}'
    lines = [
        '# Written by build-linux.py; do not edit.',
        'ninja_required_version = 1.10',
        f'builddir = {npath(out)}',
        'cc = clang',
        f'genflags = -O{guest_opt} {" ".join(GEN_FLAGS)} {march} {inc}' + (f' {guest_flags}' if guest_flags else ''),
        f'rtflags = {" ".join(RT_FLAGS)} {march} -DRT_CPU_LEVEL={3 if cpu == "v3" else 2} {rt_inc}{rt_extra}',
        f'ldflags = {" ".join(LINK_FLAGS)} -Wl,-Map={npath(out / (exe + ".map"))}{ld_extra}'
        + (f' {link_flags}' if link_flags else ''),
        f'libs = {" ".join(LINK_LIBS)}{libs_extra}',
        '',
        'rule cc_gen', '  command = $cc $genflags -MD -MF $out.d -c $in -o $out', '  deps = gcc', '  depfile = $out.d',
        '  description = CC $in', '',
        'rule cc_rt', '  command = $cc $rtflags -MD -MF $out.d -c $in -o $out', '  deps = gcc', '  depfile = $out.d',
        '  description = CC $in', '',
        'rule link', '  command = $cc $ldflags @$out.rsp $libs -o $out', '  rspfile = $out.rsp',
        '  rspfile_content = $in_newline', '  description = LINK $out', '',
    ]
    objs = []
    if guest_obj is None and (guest_opt != '1' or guest_flags):
        guest_obj = 'guest-' + guest_tag(guest_opt, guest_flags)
    guest_dir = out / 'obj' / guest_obj if guest_obj else out / 'obj'
    for mod in MODULES:
        for f in sorted((lift / mod).glob('*.c')):
            o = guest_dir / mod / (f.stem + '.o')
            lines.append(f'build {npath(o)}: cc_gen {npath(f)}')
            objs.append(o)
    sources = runtime_sources(runtime) + [gen / 'modules.c'] + EXTRA_SOURCES
    for s in sources:
        rel = s.relative_to(runtime) if s.is_relative_to(runtime) else Path(s.name)
        o = out / 'obj' / rt_obj / rel.with_suffix('.o')
        lines.append(f'build {npath(o)}: cc_rt {npath(s)}')
        extra = PER_FILE_DEFINES.get(rel.as_posix())
        if extra:
            lines.append(f'  rtflags = $rtflags {extra}')
        flags = PER_FILE_FLAGS.get(rel.as_posix())
        if flags:
            lines.append(f'  rtflags = {" ".join(flags)} -DRT_CPU_LEVEL={3 if cpu == "v3" else 2} {rt_inc}{rt_extra}')
        objs.append(o)
    exe = out / exe
    lines += [f'build {npath(exe)}: link ' + ' '.join(npath(o) for o in objs), f'default {npath(exe)}', '']
    out.mkdir(parents=True, exist_ok=True)
    ninja = out / ('build.ninja' if exe.name == 'nx2navi' else f'build.{exe.name}.ninja')
    ninja.write_text('\n'.join(lines), encoding='utf-8')
    return ninja


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
    ap.add_argument('--exe', default='nx2navi', help='the binary name in <out> (default nx2navi)')
    ap.add_argument('--tracy', action='store_true', help='build with the Tracy client (NX2NAVI_TRACY_PREFIX)')
    ap.add_argument('--rt-obj', help='runtime objects under obj/<name> (default runtime; runtime-tracy with --tracy): a build beside another one')
    ap.add_argument('--guest-opt', choices=('1', '2', '3'), default='1', help='-O level of the lifted game code (default 1)')
    ap.add_argument('--guest-flags', default='', help='appended to the lifted code\'s compile line, e.g. -march=znver3')
    ap.add_argument('--guest-obj', help='game objects under obj/<name> (default obj/ at the stock flags, else guest-<level and flags>)')
    ap.add_argument('--no-ccache', action='store_true', help='compile without ccache')
    ap.add_argument('--link-flags', default='', help='appended to the link line')
    a = ap.parse_args()
    src = a.src.resolve()
    extracted = (a.extracted or src / 'build' / 'extracted' / 'v111').resolve()
    out = (a.out or src / 'build' / 'v111').resolve()
    py = (a.python or src / '.venv' / 'bin' / 'python').absolute()   # not resolve(): a venv's python is a symlink
    lift = extracted / 'build-cache' / 'lift'
    step_lift(src, py, extracted)
    gen = step_glue(src, py, extracted, out, lift)
    tracy = None
    if a.tracy:
        tracy = Path(os.environ.get('NX2NAVI_TRACY_PREFIX') or '')
        if not (tracy / 'lib' / 'libTracyClient.so').is_file():
            sys.exit('build-linux: --tracy needs NX2NAVI_TRACY_PREFIX (the nixpkgs tracy store path; the flake sets it)')
    ninja = write_ninja(src, out, lift, gen, a.cpu, a.exe, tracy, a.rt_obj, a.guest_opt, a.guest_flags, a.guest_obj,
                        a.link_flags)
    run(['ninja', '-C', out, '-f', ninja.name, f'-j{a.jobs}'], env=None if a.no_ccache else ccache_env(src))
    step_copy(src, out)
    print(f'\nbuild-linux: {out / a.exe} ({(out / a.exe).stat().st_size / 1e6:.0f} MB)')


if __name__ == '__main__':
    main()
