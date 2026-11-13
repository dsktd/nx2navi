import re,sys
def win(p):
    s=open(p,errors='replace').read(); W={}
    for m in re.finditer(r"perf: frame (\d+): interval avg ([\d.]+) ms.*?textures uploaded (\d+) re-uploaded (\d+).*?replay avg ([\d.]+) ms",s):
        W[int(m[1])]=dict(fps=1000/float(m[2]),rep=float(m[5]),up=int(m[3]),reup=int(m[4]))
    for m in re.finditer(r"perf: frame (\d+): gpu avg ([\d.]+) ms",s):
        W.setdefault(int(m[1]),{})['gpu']=float(m[2])
    for m in re.finditer(r"perf: frame (\d+): work in the window.*?file reads ([\d.]+) ms \((\d+),",s):
        W.setdefault(int(m[1]),{})['files']=int(m[3])
    return {f:w for f,w in W.items() if 'fps' in w and f>300}
for p in sys.argv[1:]:
    W=win(p); lo=int(__import__('os').environ.get('LO',0)); hi=int(__import__('os').environ.get('HI',10**9))
    r=[w for f,w in W.items() if lo<=f<=hi]; n=len(r)
    m=lambda k:sum(w.get(k,0) for w in r)/n
    print(f"{p[-34:]:34s} n={n} fps {m('fps'):.1f} <60 {100*sum(w['fps']<60 for w in r)/n:.0f}% <50 {100*sum(w['fps']<50 for w in r)/n:.0f}% replay {m('rep'):.1f} gpu {m('gpu'):.1f} files/60 {m('files'):.0f} up/60 {m('up'):.0f} reup/60 {m('reup'):.1f}")
