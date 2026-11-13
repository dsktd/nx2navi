#!/bin/bash
# offline-test.sh (root): build on the Deck with no network (unshare -n), then one field cell with every packet but
# ssh and loopback dropped (nft table inet nx2cut, removed at the end and by a 20 min timer), and count link bytes
O=/home/deck/nx2navi/runs/offline-test.out; : > $O; chown deck:deck $O
bytes() { cat /sys/class/net/{wlan0,wg0,enp4s0f3u1u4c2}/statistics/{rx,tx}_bytes 2>/dev/null | awk "{s+=\$1} END {print s}"; }
b0=$(bytes); t0=$(date +%s)
echo "build (unshare -n): $(unshare -n -- sudo -u deck env HOME=/home/deck /home/deck/nx2navi/deckbuild.sh deck3 /home/deck/nx2navi/p1.mbox 2>&1 | tail -2 | tr '\n' ' ')" >> $O
echo "build took $(( $(date +%s) - t0 )) s" >> $O
systemd-run --quiet --on-active=1200 --unit=nx2cut-off nft delete table inet nx2cut
nft -f - <<'N'
table inet nx2cut {
  chain out { type filter hook output priority 0; policy drop; oifname "lo" accept; tcp sport 22 accept; }
  chain in { type filter hook input priority 0; policy drop; iifname "lo" accept; tcp dport 22 accept; }
}
N
echo "cut on: $(ping -c1 -W2 1.1.1.1 >/dev/null 2>&1 && echo 'ping still works' || echo 'ping fails as intended')" >> $O
sudo -u deck env HOME=/home/deck XDG_RUNTIME_DIR=/run/user/1000 EXE=deck3 LOWMEM=300 TMO=420 /home/deck/nx2navi/cell.sh field-mid-standing off1 4200 >> $O 2>&1
nft delete table inet nx2cut; systemctl stop nx2cut-off.timer 2>/dev/null
echo "cut off; link bytes during the test: $(( $(bytes) - b0 )) in $(( $(date +%s) - t0 )) s" >> $O
echo BGDONE >> $O
