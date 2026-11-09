set pagination off
# tools/voice-queue.gdb (#128 pass 4): the sound thread (f_70036d52d0) pops two lock-free queues at [[this]+0x1b8]+0x80000 (+0x348..
# and +0x3b8..; producer tails +0x360 and +0x3d0). From the slot-20 voice start on, hw watch both tails: each push prints the
# pushing thread's bt and guest fp chain, which is the game-thread site that starts a narration line. Stops after the slot-21 start.
# GDB_SCRIPT=tools/voice-queue.gdb LAB_EXE=nx2navi.gdbwrap tools/lab-run ...
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
set $base = 0
set $n = 0
break f_70036d52d0
commands
  silent
  set $this = (unsigned long)kern_cpu()->x[0]
  set $base = *(unsigned long*)(*(unsigned long*)$this + 0x1b8) + 0x80000
  printf "=== sound frame this=%lx queue base=%lx tails %lx %lx\n", $this, $base, *(unsigned long*)($base+0x360), *(unsigned long*)($base+0x3d0)
  delete 1
  continue
end
break update_voice
commands
  silent
  set $r = r
  watch -l $r->voices[20].state
  commands
    silent
    printf "=== WATCH slot20 state %d\n", $r->voices[20].state
    if $r->voices[20].state == 1 && $base != 0
      watch -l *(unsigned long*)($base+0x360)
      commands
        silent
        set $n = $n + 1
        printf "=== PUSH q1 tail=%lx n=%d\n", *(unsigned long*)($base+0x360), $n
        bt 16
        gwalk
        continue
      end
      watch -l *(unsigned long*)($base+0x3d0)
      commands
        silent
        set $n = $n + 1
        printf "=== PUSH q2 tail=%lx n=%d\n", *(unsigned long*)($base+0x3d0), $n
        bt 16
        gwalk
        continue
      end
    end
    continue
  end
  watch -l $r->voices[21].state
  commands
    silent
    printf "=== WATCH slot21 state %d\n", $r->voices[21].state
    shell date +%s.%N
    if $r->voices[21].state == 1
      delete
    end
    continue
  end
  delete 2
  continue
end
run
printf "=== end\n"
