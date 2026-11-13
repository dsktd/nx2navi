#!/bin/bash
# deckbuild.sh <name> [patch.mbox ...]: build NX2navi ON the Deck, offline. The tree mirrors the desktop's paths
# (/home/purplg/claude/nx2navi: sources .lab/wt-deck, objects NX2navi/build/v111-rebase4, .ccache) and the toolchain is
# the flake's dev shell copied into /nix/store, entered through devenv.sh (nix print-dev-env; no nix needed here).
# Patches (git format-patch mboxes) are applied to .lab/wt-deck with git am first. Result: ~/nx2navi/build/v111/nx2navi.<name>
set -eu
R=/home/purplg/claude/nx2navi; W=$R/.lab/wt-deck; n=$1; shift
exec 8>/home/deck/nx2navi/.build.lock; flock 8
for p; do git -C $W am -q "$p"; done
cd $R/NX2navi
[ -e build/extracted-rebase/v111/romfs ] || ln -s /home/deck/nx2navi/build/extracted/v111/romfs build/extracted-rebase/v111/romfs
env -i HOME=$HOME bash -c "source /home/deck/nx2navi/devenv.sh >/dev/null 2>&1; export HOME=$HOME; cd $R/NX2navi && nice -n 10 python3 -I $R/build-linux.py --src $W --extracted $R/NX2navi/build/extracted-rebase/v111 --out $R/NX2navi/build/v111-rebase4 --exe nx2navi.$n --rt-obj runtime-deck2 --python $R/NX2navi/.venv/bin/python --jobs 6" > /home/deck/nx2navi/runs/build-$n.log 2>&1 || { grep -B2 -A12 "error:\|FAILED" /home/deck/nx2navi/runs/build-$n.log | head -50; echo "deckbuild: failed"; exit 1; }
cp $R/NX2navi/build/v111-rebase4/nx2navi.$n /home/deck/nx2navi/build/v111/nx2navi.$n.tmp && mv /home/deck/nx2navi/build/v111/nx2navi.$n.tmp /home/deck/nx2navi/build/v111/nx2navi.$n
echo "deckbuild: nx2navi.$n $(git -C $W log --oneline -1 | cut -c1-60) $(sha256sum /home/deck/nx2navi/build/v111/nx2navi.$n | cut -c1-12)"
