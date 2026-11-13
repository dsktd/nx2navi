#!/bin/sh
# bg.sh <name> <command...>: run as a transient user unit (an ssh session's leftovers are killed when it closes);
# output in ~/nx2navi/runs/<name>.out, "BGDONE" at the end. Stop: systemctl --user stop nx2navi-<name>
N=$HOME/nx2navi; mkdir -p $N/runs; n=$1; shift; : > $N/runs/$n.out
export XDG_RUNTIME_DIR=/run/user/$(id -u)
exec systemd-run --user --quiet --collect --unit=nx2navi-$n --working-directory=$N \
  sh -c '"$@" >> "$0" 2>&1; echo BGDONE >> "$0"' $N/runs/$n.out "$@"
