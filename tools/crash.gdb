# just debug: the game under gdb. Guest write-watch faults are the runtime's business (SIGSEGV passes through
# silently); a real crash reaches the runtime's crash reporter, where we record every thread's host backtrace.
set pagination off
set print thread-events off
set disable-randomization off
handle all nostop noprint pass
handle SIGTRAP SIGINT stop print nopass
break crash_handler
commands
  silent
  printf "=== crash: %s at host %#lx addr %#lx\n", x->what, x->rip, x->addr
  bt 40
  info registers rip rsp rbp
  thread apply all bt 12
  continue
end
break rt_fatal
commands
  silent
  printf "=== rt_fatal\n"
  bt 30
  continue
end
run
printf "=== end\n"
