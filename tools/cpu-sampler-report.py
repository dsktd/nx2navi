#!/usr/bin/env python3
"""cpu-sampler-report.py <samples.txt> [top]: self time per function (and per inlined source function) of a
cpu-sampler.so run. Addresses in the game binary (no-pie) and in shared libraries are resolved with
llvm-symbolizer through <samples.txt>.maps; needs llvm-symbolizer on PATH (nix shell nixpkgs#llvm)."""
import collections
import subprocess
import sys

path = sys.argv[1]
top = int(sys.argv[2]) if len(sys.argv) > 2 else 15
maps = []
for line in open(path + '.maps'):
    f = line.split()
    if len(f) >= 6 and 'x' in f[1]:
        lo, hi = (int(x, 16) for x in f[0].split('-'))
        maps.append((lo, hi, int(f[2], 16), f[5]))
rips = collections.Counter(int(line.split()[0], 16) for line in open(path) if line.strip())
total = sum(rips.values())


def module(a):
    for lo, hi, off, name in maps:
        if lo <= a < hi:
            return name, (a if name.endswith('/nx2navi') or '/nx2navi.' in name else a - lo + off)
    return '?', a


by_mod = collections.defaultdict(list)
for a in rips:
    m, rel = module(a)
    by_mod[m].append((a, rel))
outer = collections.Counter()
inner = collections.Counter()
for m, addrs in by_mod.items():
    short = m.rsplit('/', 1)[-1]
    if m == '?' or not m.startswith('/'):
        for a, _ in addrs:
            outer[f'{short} ?'] += rips[a]
        continue
    q = '\n'.join(f'0x{rel:x}' for _, rel in addrs)
    out = subprocess.run(['llvm-symbolizer', '--obj', m, '--inlining', '--functions=linkage', '--demangle'],
                         input=q, capture_output=True, text=True).stdout.split('\n\n')
    for (a, _), block in zip(addrs, out):
        lines = block.strip().split('\n')
        frames = [(lines[i], lines[i + 1] if i + 1 < len(lines) else '') for i in range(0, len(lines), 2)]
        if not frames or frames[0][0] == '??':
            outer[f'{short} ?'] += rips[a]
            continue
        fn, loc = frames[-1]
        tag = '' if short.startswith('nx2navi') else f' [{short}]'
        outer[f'{fn}{tag}'] += rips[a]
        ifn, iloc = frames[0]
        inner[f'{ifn} {iloc.rsplit("/", 1)[-1]}{tag}'] += rips[a]
print(f'{total} samples')
print('self time by function (inlined code counted in its caller):')
for k, v in outer.most_common(top):
    print(f'  {100 * v / total:5.1f}%  {k}')
print('self time by source line (innermost inlined function):')
for k, v in inner.most_common(top):
    print(f'  {100 * v / total:5.1f}%  {k}')
