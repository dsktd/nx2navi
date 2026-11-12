import re,sys,statistics as st
for f in sys.argv[1:]:
    W={}
    for l in open(f,errors='replace'):
        m=re.search(r'frame (\d+): interval avg ([\d.]+) ms max ([\d.]+)',l)
        if m: W.setdefault(int(m[1]),{}).update(iv=float(m[2]),mx=float(m[3])); continue
        m=re.search(r'write-watch frame (\d+): per frame, every consumer: ([\d.]+) queries over ([\d.]+) MiB, ([\d.]+) ms',l)
        if m: W.setdefault(int(m[1]),{}).update(ww=float(m[4]),wwmb=float(m[3])); continue
        m=re.search(r'shadow at frame (\d+):.*?(\d+) pool syncs.*?([\d.]+) MiB copied in.*?, ([\d.]+) ms',l)
        if m: W.setdefault(int(m[1]),{}).update(sh=float(m[4])/60,shmb=float(m[3])/60); continue
        m=re.search(r'frame (\d+): gpu avg ([\d.]+) ms',l)
        if m: W.setdefault(int(m[1]),{}).update(gpu=float(m[2])); continue
        m=re.search(r'frame (\d+): binding storage checks (\d+)',l)
        if m: W.setdefault(int(m[1]),{}).update(chk=float(m[2])/60)
    rows=[v for k,v in sorted(W.items()) if k>=1200 and all(x in v for x in('iv','ww','sh','gpu','chk'))]
    print(f, len(rows))
    def c(a,b):
        return st.correlation([r[a] for r in rows],[r[b] for r in rows])
    for k in ('mx','ww','wwmb','sh','shmb','gpu','chk'):
        if all(k in r for r in rows): print(" corr(interval,%s)=%.2f"%(k,c('iv',k)))
    rows.sort(key=lambda r:r['iv'])
    for name,part in (('fast',rows[:len(rows)//4]),('slow',rows[-len(rows)//4:])):
        print(" %s: "%name+" ".join("%s %.2f"%(k,st.mean(r[k] for r in part)) for k in ('iv','gpu','ww','wwmb','sh','shmb','chk')))
