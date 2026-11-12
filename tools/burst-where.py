import sys,importlib.machinery,importlib.util
l=importlib.machinery.SourceFileLoader("bs","/home/purplg/claude/nx2navi/tools/burst-scan")
s=importlib.util.spec_from_loader("bs",l); m=importlib.util.module_from_spec(s); l.exec_module(m)
d="/home/purplg/claude/nx2navi/NX2navi/build/v111/logs/burst-2808/"
for a,b in ((2743,2745),(2744,2746),(2752,2754),(2784,2786)):
    w,h,x=m.read_png(d+"%d.png"%a); _,_,y=m.read_png(d+"%d.png"%b); bpp=len(x)//(w*h)
    g=[[0]*4 for _ in range(3)]
    for j in range(h):
        for i in range(w):
            k=(j*w+i)*bpp; g[j*3//h][i*4//w]+=abs(x[k+1]-y[k+1])
    n=w*h/12; print(a,b,[" ".join("%5.1f"%(v/n) for v in r) for r in g])
