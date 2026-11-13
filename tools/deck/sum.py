import re, sys
log, lo, hi = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
iv, win = [], {}
for s in open(log, errors='replace'):
    m = re.search(r'present: frame (\d+) interval ([\d.]+) ms', s)
    if m and lo < int(m[1]) < hi: iv.append(float(m[2])); continue
    m = re.search(r'perf: frame (\d+): (?:interval avg ([\d.]+)|gpu avg ([\d.]+))', s)
    if m and lo < int(m[1]) < hi:
        w = win.setdefault(int(m[1]), {})
        if m[2]: w['iv'] = float(m[2]); r = re.search(r'replay avg ([\d.]+)', s); w['rp'] = float(r[1]) if r else 0
        else: w['gpu'] = float(m[3])
if len(iv) < 60: print('status=short frames=%d' % len(iv)); sys.exit()
tot = sum(iv); srt = sorted(iv); p99 = srt[min(len(srt) - 1, int(len(srt) * 0.99))]
# min fps over 1 s windows of summed intervals
secs, acc, n = [], 0.0, 0
for x in iv:
    acc += x; n += 1
    if acc >= 1000: secs.append(1000 * n / acc); acc, n = 0.0, 0
w = [x for x in win.values() if 'iv' in x and 'gpu' in x]
avg = lambda k: sum(x[k] for x in w) / len(w) if w else 0
print('status=ok frames=%d fps=%.2f min1s=%.2f low1=%.2f over25_min=%.1f interval_ms=%.2f replay_ms=%.2f gpu_ms=%.2f windows=%d' % (
    len(iv), 1000 * len(iv) / tot, min(secs) if secs else 0, 1000 / p99, sum(x > 25 for x in iv) * 60000 / tot, avg('iv'), avg('rp'), avg('gpu'), len(w)))
