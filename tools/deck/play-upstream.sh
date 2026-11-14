#!/bin/sh
# "NX2navi (upstream)" on the Steam Deck: unpatched upstream v0.10.1 (5ae55db) as tools/make_game.py builds it
# (docs/README-BuildKit.md "Linux"), folder ~/nx2navi/upstream. The permanent performance reference: never patch it.
# No NX2NAVI_ settings here: nx2navi.ini (upstream's example, all defaults), profile/, mesa-cache/ beside the game.
# Only deviation from the docs: the game was built in the desktop's Nix shell, so its libraries come from the copied
# Nix closure (libs.sh) and the Vulkan driver through nixVulkanIntel, as for the patched entry.
U=$HOME/nx2navi/upstream; cd "$U" || exit 1; mkdir -p logs
unset LD_PRELOAD LD_LIBRARY_PATH
exec 9>"$HOME/nx2navi/.game.lock"; flock -n 9 || { echo "NX2navi is already running" >&2; exit 3; }
exec /nix/store/ynczmb6i3kjia50k0hv19biblhjdnly9-nixVulkanIntel/bin/nixVulkanIntel $HOME/nx2navi/libs.sh ./ocarina "$@" > "logs/steam-$(date +%Y%m%d-%H%M%S).log" 2>&1
