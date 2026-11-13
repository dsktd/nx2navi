# sumarms.py <tag>...: mean (min..max) over runs/<tag>-*/sum.txt
import glob, os, statistics as st, sys
N = os.path.expanduser('~/nx2navi/runs')
for tag in sys.argv[1:]:
    rows = [dict(kv.split('=') for kv in open(f).read().split()) for f in sorted(glob.glob(f'{N}/{tag}-[0-9]*/sum.txt'))]
    bad = [r for r in rows if r.get('status') != 'ok']; rows = [r for r in rows if r.get('status') == 'ok']
    if not rows: print(f'{tag}: no ok runs ({len(bad)} bad)'); continue
    out = [f'{tag} n={len(rows)}' + (f' bad={len(bad)}' if bad else '')]
    for k in ['fps', 'min1s', 'low1', 'over25_min', 'interval_ms', 'replay_ms', 'gpu_ms']:
        v = [float(r[k]) for r in rows]; out.append(f'{k} {st.mean(v):.1f} ({min(v):.1f}..{max(v):.1f})')
    print('; '.join(out))
