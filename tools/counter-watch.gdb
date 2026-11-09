# tools/counter-watch.gdb (#128): awatch on the update object's +0xd50 once the game runs (perf_present). Run the game under
# gdb from the game dir: `gdb -q -batch -x tools/counter-watch.gdb --args ./nx2navi.new` (as LAB_EXE through a wrapper script in
# the game dir). Addresses are the deterministic heap ones of this build (tools/counter-sample prints them).
set pagination off
set print thread-events off
set disable-randomization on
handle all nostop noprint pass
handle SIGTRAP SIGINT stop print nopass
set can-use-hw-watchpoints 1
break perf_present
commands
  silent
  awatch *(int*)(0x1373cd100+0xd50)
  commands
    silent
    printf "HIT upd50 pc=%p ", $pc
    x/i $pc
    continue
  end
  delete 1
  continue
end
run
printf "=== end\n"
