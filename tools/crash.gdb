set pagination off
set disable-randomization off
set print thread-events off
handle all nostop noprint pass
handle SIGSEGV SIGBUS SIGABRT SIGILL SIGFPE stop print pass
handle SIGTRAP SIGINT stop print nopass
set $n = 0
catch signal SIGSEGV SIGBUS SIGABRT SIGILL SIGFPE
commands
  silent
  set $n = $n + 1
  printf "=== signal stop %d\n", $n
  p $_siginfo.si_signo
  p $_siginfo._sifields._sigfault.si_addr
  x/i $pc
  bt 30
  info registers rsp rbp
  info threads
  if $n < 40
    continue
  end
end
run
printf "=== end, %d stops\n", $n
