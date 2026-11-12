import sys,glob,importlib.machinery,importlib.util,os
l=importlib.machinery.SourceFileLoader("bs","/home/purplg/claude/nx2navi/tools/burst-scan")
s=importlib.util.spec_from_loader("bs",l); m=importlib.util.module_from_spec(s); l.exec_module(m)
d=sys.argv[1]; fs=sorted(glob.glob(d+"/*.png"),key=lambda p:int(os.path.basename(p)[:-4]))
def g(p):
    r=m.read_png(p); return r
print(type(g(fs[0])), [type(x) for x in g(fs[0])][:4] if isinstance(g(fs[0]),tuple) else '')
W,H,px=g(fs[0]); bpp=len(px)//(W*H)
def lum(p):
    w,h,b=g(p); y0=int(os.environ.get("Y0","0"))*h//3; y1=y0+h//3; out=[]
    for y in range(y0,y1):
        row=b[(y*w)*bpp:(y*w+w)*bpp]; out+= [row[i*bpp+1] for i in range(0,w,2)]
    return out
a=[lum(f) for f in fs]
def dif(x,y): return sum(abs(p-q) for p,q in zip(x,y))/len(x)
r=[]
for i in range(1,len(a)-1):
    dp,dn,ds=dif(a[i],a[i-1]),dif(a[i],a[i+1]),dif(a[i-1],a[i+1]); r.append((min(dp,dn)-ds,os.path.basename(fs[i]),dp,dn,ds))
for x in sorted(r,reverse=True)[:6]: print("%s blink %.2f prev %.2f next %.2f skip %.2f"%x[1:2]+x[0:1]+x[2:] if False else "%s blink %.2f prev %.2f next %.2f skip %.2f"%(x[1],x[0],x[2],x[3],x[4]))
print(" ".join("%s:%.1f/%.1f"%(os.path.basename(fs[i])[:-4],r[i-1][2],r[i-1][4]) for i in range(1,len(a)-1)))
