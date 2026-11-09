set pagination off
# tools/voice-stream.gdb (#128 pass 4): hw watches on the stream-reader entry that served narration slot 21 in pass 4's heap scan
# (0x1ac7855e0: +0x20 buffer-ring object, +0x30 open flag, +0x40 handle; ring object 0x1ade21d58's first buffer at 0x1ade21d70;
# heap addresses are deterministic). Each write prints the writer's bt and guest chain; the one before "counters: voice 21 start"
# is the game-side decision to open the line. GDB_SCRIPT=tools/voice-stream.gdb LAB_EXE=nx2navi.gdbwrap tools/lab-run ...
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
define onhit
  shell date +%s.%N
  bt 20
  gwalk
  continue
end
break f_70036d52d0
commands
  silent
  delete 1
  watch -l *(unsigned long*)0x1ac785600
  commands
    silent
    printf "=== WRITE +0x20 = %lx\n", *(unsigned long*)0x1ac785600
    onhit
  end
  watch -l *(unsigned long*)0x1ac785610
  commands
    silent
    printf "=== WRITE +0x30 = %lx\n", *(unsigned long*)0x1ac785610
    onhit
  end
  watch -l *(unsigned long*)0x1ac785620
  commands
    silent
    printf "=== WRITE +0x40 = %lx\n", *(unsigned long*)0x1ac785620
    onhit
  end
  watch -l *(unsigned long*)0x1ade21d70
  commands
    silent
    printf "=== WRITE ring+0x18 = %lx\n", *(unsigned long*)0x1ade21d70
    onhit
  end
  continue
end
run
printf "=== end\n"
