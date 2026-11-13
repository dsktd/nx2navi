# stable.py <run.log> <min frame>: prints the frame of the newest perf window once the last 3 windows (60 frames each)
# after <min frame> have interval averages within 3% of their mean, built no pipelines and show the scene (GPU time
# of 3 ms or more a frame: a loading screen is steady too); nothing otherwise
import re, sys
w, g = [], {}
for s in open(sys.argv[1], errors='replace'):
    m = re.search(r'perf: frame (\d+): interval avg ([\d.]+) ms.*pipelines built in background (\d+)', s)
    if m and int(m[1]) >= int(sys.argv[2]): w.append((int(m[1]), float(m[2]), int(m[3]))); continue
    m = re.search(r'perf: frame (\d+): gpu avg ([\d.]+) ms', s)
    if m: g[int(m[1])] = float(m[2])
if len(w) >= 3:
    t = w[-3:]; mean = sum(x[1] for x in t) / 3
    if all(abs(x[1] - mean) <= 0.03 * mean and x[2] == 0 and g.get(x[0], 0) >= 3 for x in t): print(t[-1][0])
