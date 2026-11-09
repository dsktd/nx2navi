set pagination off
# tools/voice-watch.gdb (#128 pass 3): hw watchpoints on the server voice slots 20-22 (state), set from the first update_voice; each
# change prints the host bt (lifted f_<guest addr> frames) and the guest fp chain (gwalk: kern_cpu()->x[29]). Run through tools/gdbwrap
# copied into the game dir: GDB_SCRIPT=tools/voice-watch.gdb LAB_EXE=nx2navi.gdbwrap tools/lab-run ...
set print thread-events off
set disable-randomization on
set confirm off
handle all nostop noprint pass
handle SIGTRAP SIGINT stop print nopass
set can-use-hw-watchpoints 1
python
import gdb
class Walk(gdb.Command):
    def __init__(self): super().__init__('gwalk', gdb.COMMAND_USER)
    def invoke(self, arg, tty):
        c = gdb.parse_and_eval('kern_cpu()')
        if int(c) == 0:
            print('guest: no cpu (host thread)'); return
        fp = int(c['x'][29]); print('guest: pc=%x lr=%x sp=%x fp=%x x0=%x x19=%x x20=%x' % (int(c['pc']), int(c['x'][30]), int(c['sp']), fp, int(c['x'][0]), int(c['x'][19]), int(c['x'][20])))
        for i in range(40):
            try:
                nfp = int(gdb.parse_and_eval('*(unsigned long*)%d' % fp)); l = int(gdb.parse_and_eval('*(unsigned long*)%d' % (fp + 8)))
            except Exception:
                break
            print('  guest frame fp=%x lr=%x' % (fp, l))
            if nfp <= fp or nfp == 0: break
            fp = nfp
Walk()
end
break update_voice
commands
  silent
  set $r = r
  watch -l $r->voices[20].state
  commands
    silent
    printf "=== WATCH slot20 state %d t=", $r->voices[20].state
    shell date +%s.%N
    bt 30
    gwalk
    continue
  end
  watch -l $r->voices[21].state
  commands
    silent
    printf "=== WATCH slot21 state %d\n", $r->voices[21].state
    bt 30
    gwalk
    x/80gx kern_cpu()->sp
    thread apply all bt 10
    continue
  end
  watch -l $r->voices[22].state
  commands
    silent
    printf "=== WATCH slot22 state %d\n", $r->voices[22].state
    bt 30
    gwalk
    continue
  end
  delete 1
  continue
end
run
printf "=== end\n"
