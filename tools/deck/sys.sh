#!/bin/sh
# NX2navi system switches for the Steam Deck. Root only; every switch is a runtime value that a reboot resets,
# unless `persist` wrote /etc/tmpfiles.d/nx2navi.conf (undo: `sys.sh unpersist`). Log: ~/nx2navi/SYSTEM-CHANGES.md
#   sys.sh show
#   sys.sh udmabuf <MiB>        size limit of one udmabuf (stock 64; the game's dma-buf path needs >= 1024)
#   sys.sh epp <pref>           amd-pstate EPP of every core (stock balance_performance; performance)
#   sys.sh gpu <auto|high>      amdgpu power level (stock auto)
#   sys.sh gtt <GiB|stock>     GPU memory limit (ttm.pages_limit; stock 8): set now and on the kernel command line
#                              (/etc/default/grub + update-grub, backup /etc/default/grub.nx2navi-bak); reboot to be sure
#   sys.sh persist | unpersist  keep the current udmabuf value across reboots, or drop that again
set -eu
U=/sys/module/udmabuf/parameters/size_limit_mb
G=$(ls /sys/class/drm/card*/device/power_dpm_force_performance_level | head -1)
T=/etc/tmpfiles.d/nx2navi.conf
case "${1:-show}" in
show) echo "gtt $(( $(cat /sys/module/ttm/parameters/pages_limit) / 262144 )) GiB (cmdline: $(grep -o "ttm.pages_limit=[0-9]*" /proc/cmdline || echo stock))"; echo "udmabuf $(cat $U)"; echo "epp $(cat /sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference)"
      echo "gpu $(cat $G)"; [ -f $T ] && echo "persist: $(cat $T)" || echo "persist: none";;
udmabuf) case "$2" in *[!0-9]*|'') exit 2;; esac; echo "$2" > $U;;
epp) case "$2" in performance|balance_performance|balance_power|power|default) ;; *) exit 2;; esac
     for f in /sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference; do echo "$2" > $f; done;;
gpu) case "$2" in auto|high) echo "$2" > $G;; *) exit 2;; esac;;
gtt) D=/etc/default/grub; [ -f $D.nx2navi-bak ] || cp -p $D $D.nx2navi-bak
     sed -i 's/ ttm\.pages_limit=[0-9]*//' $D
     case "$2" in
     stock) echo 2097152 > /sys/module/ttm/parameters/pages_limit;;
     *[!0-9]*|'') exit 2;;
     *) [ "$2" -ge 8 ] && [ "$2" -le 13 ] || exit 2; n=$(( $2 * 262144 ))
        sed -i "s/^GRUB_CMDLINE_LINUX_DEFAULT=\"\(.*\)\"/GRUB_CMDLINE_LINUX_DEFAULT=\"\1 ttm.pages_limit=$n\"/" $D
        echo $n > /sys/module/ttm/parameters/pages_limit;;
     esac
     grep ^GRUB_CMDLINE_LINUX_DEFAULT $D; update-grub;;
persist) echo "w $U - - - - $(cat $U)" > $T;;
unpersist) rm -f $T;;
*) exit 2;;
esac
