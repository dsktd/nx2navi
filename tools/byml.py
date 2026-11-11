import struct
def load(b):
    E='<' if b[:2]==b'YB' else '>'
    ver,keyo,stro,root=struct.unpack_from(E+'HIII',b,2)
    def strtab(o):
        if not o: return []
        n=int.from_bytes(b[o+1:o+4],'little' if E=='<' else 'big')
        offs=struct.unpack_from(E+'%dI'%(n+1),b,o+4)
        return [b[o+x:b.index(b'\0',o+x)].decode() for x in offs[:n]]
    keys=strtab(keyo); strs=strtab(stro)
    def val(t,v,at):
        if t==0xA0: return strs[v]
        if t in(0xC0,0xC1,0xC2,0xC3): return node(v)
        if t==0xD0: return bool(v)
        if t==0xD1: return struct.unpack(E+'i',struct.pack(E+'I',v))[0]
        if t==0xD2: return struct.unpack(E+'f',struct.pack(E+'I',v))[0]
        if t==0xD3: return v
        if t in(0xD4,0xD5,0xD6):
            raw=b[v:v+8]; return struct.unpack(E+{0xD4:'q',0xD5:'Q',0xD6:'d'}[t],raw)[0]
        if t==0xFF: return None
        return ('?%x'%t,v)
    def node(o):
        t=b[o]; n=int.from_bytes(b[o+1:o+4],'little' if E=='<' else 'big')
        if t==0xC0:
            ts=b[o+4:o+4+n]; base=(o+4+n+3)&~3
            return [val(ts[i],struct.unpack_from(E+'I',b,base+4*i)[0],base+4*i) for i in range(n)]
        if t==0xC1:
            out={}
            for i in range(n):
                e=o+4+8*i; k=int.from_bytes(b[e:e+3],'little') if E=='<' else int.from_bytes(b[e:e+3],'big'); tt=b[e+3]; v=struct.unpack_from(E+'I',b,e+4)[0]
                out[keys[k]]=val(tt,v,e+4)
            return out
        if t in(0x20,0x21):  # hash maps: key u32/u64, value, type array after
            ks=4 if t==0x20 else 8; out={}
            ent=o+4; tsb=ent+n*(ks+4)
            for i in range(n):
                e=ent+i*(ks+4); k=int.from_bytes(b[e:e+ks],'little' if E=='<' else 'big'); v=struct.unpack_from(E+'I',b,e+ks)[0]
                out[hex(k)]=val(b[tsb+i],v,e+ks)
            return out
        return ('?node%x'%t,o)
    return node(root)
