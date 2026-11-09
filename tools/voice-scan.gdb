set pagination off
# tools/voice-scan.gdb (#128 pass 4): at the slot-21 voice start (hw watch, see voice-watch.gdb) scan the guest heap for the narration
# wave-buffer addresses the counters trace prints, to locate the atk StreamSound/player objects; prints each hit with context
# and the pointers into its object (one level). GDB_SCRIPT=tools/voice-scan.gdb LAB_EXE=nx2navi.gdbwrap tools/lab-run ...
set print thread-events off
set disable-randomization on
set confirm off
handle all nostop noprint pass
handle SIGTRAP SIGINT stop print nopass
set can-use-hw-watchpoints 1
python
import gdb, struct, time
def maps():
    pid = gdb.selected_inferior().pid
    out = []
    for l in open('/proc/%d/maps' % pid):
        a, b = [int(x, 16) for x in l.split()[0].split('-')]
        if 'r' not in l.split()[1]: continue
        if a < 0x100000000 or a >= 0x7000000000: continue
        out.append((a, b))
    return out
def scan(values, lo=None, hi=None):
    inf = gdb.selected_inferior(); hits = {v: [] for v in values}
    pats = {v: struct.pack('<Q', v) for v in values}
    tot = 0
    for a, b in maps():
        if lo is not None and (b <= lo or a >= hi): continue
        p = a
        while p < b:
            n = min(b - p, 64 << 20)
            try: m = bytes(inf.read_memory(p, n))
            except Exception: p += n; continue
            tot += n
            for v, pat in pats.items():
                i = m.find(pat)
                while i >= 0:
                    if i % 8 == 0: hits[v].append(p + i)
                    i = m.find(pat, i + 1)
            p += n
    return hits, tot
class Scan(gdb.Command):
    def __init__(self): super().__init__('vscan', gdb.COMMAND_USER)
    def invoke(self, arg, tty):
        vals = [int(x, 0) for x in arg.split()]
        t0 = time.time(); hits, tot = scan(vals)
        print('vscan: %d MiB in %.1fs' % (tot >> 20, time.time() - t0))
        for v, hs in hits.items():
            print('value %x: %d hits' % (v, len(hs)))
            for h in hs[:12]:
                print(' hit at %x' % h)
                gdb.execute('x/48gx %d' % (h - 0x100))
        # dump the mappings that hold the hits for the offline reference scan (scratchpad/i128/scan/)
        import os, shutil
        d = os.environ.get('VSCAN_DIR', '/tmp'); os.makedirs(d, exist_ok=True)
        shutil.copy('/proc/%d/maps' % gdb.selected_inferior().pid, d + '/maps')
        done = set()
        for v, hs in hits.items():
            for h in hs:
                for a, b in maps():
                    if a <= h < b and a not in done and b - a <= (2 << 30):
                        done.add(a); gdb.execute('dump binary memory %s/%x.bin %d %d' % (d, a, a, b))
                        print('dumped %x-%x' % (a, b))
Scan()
end
break update_voice
commands
  silent
  set $r = r
  watch -l $r->voices[21].state
  commands
    silent
    printf "=== WATCH slot21 state %d\n", $r->voices[21].state
    if $r->voices[21].state == 1
      vscan 0x1ac7f3000 0x1ac7c3000 0x1ac7eb000
    end
    continue
  end
  delete 1
  continue
end
run
printf "=== end\n"
