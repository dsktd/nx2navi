# stable.py <run.log> <min frame>: prints the frame of the newest perf window (60 frames each) once the save's area is
# on screen and steady: a loading screen (GPU under 2 ms a frame) was seen after <min frame>, and the last 3 windows
# since it have interval averages within 3% of their mean, built no pipelines and GPU time of 3 ms or more; else nothing
import re, sys
w, g = [], {}
for s in open(sys.argv[1], errors='replace'):
    m = re.search(r'perf: frame (\d+): interval avg ([\d.]+) ms.*pipelines built in background (\d+)', s)
    if m: w.append((int(m[1]), float(m[2]), int(m[3]))); continue
    m = re.search(r'perf: frame (\d+): gpu avg ([\d.]+) ms', s)
    if m: g[int(m[1])] = float(m[2])
load = [x[0] for x in w if x[0] >= int(sys.argv[2]) and g.get(x[0], 99) < 2]
if load:
    t = [x for x in w if x[0] > load[-1]][-3:]
    if len(t) == 3:
        mean = sum(x[1] for x in t) / 3
        if all(abs(x[1] - mean) <= 0.03 * mean and x[2] == 0 and g.get(x[0], 0) >= 3 for x in t): print(t[-1][0])
