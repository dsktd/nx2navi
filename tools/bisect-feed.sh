#!/bin/bash
# Feed for the live screensaver while the fog-NaN bisect runs: follows the newest NX2navi run log and every new
# frame dump, and writes one readable stream (frame progress toward the dump, fog NaN count per run).
out=${1:-$HOME/claude/.services/screensavers/feeds/fog-bisect.log}
V=$HOME/claude/nx2navi/NX2navi/build/v111
frame=$HOME/claude/nx2navi/latest-frame.png
cur=""; seen=" $(ls -d $V/dump-* 2>/dev/null | tr '\n' ' ')"
: > "$out"
while true; do
    L=$(ls -t $V/logs/run-*.log 2>/dev/null | head -1)
    if [ "$L" != "$cur" ]; then
        cur=$L; echo "== run $(basename "$L" .log)" >> "$out"
        pos=$(wc -c < "$L")
    fi
    n=$(wc -c < "$cur")
    if [ "$n" -gt "$pos" ]; then
        tail -c +$((pos + 1)) "$cur" | grep -a --line-buffered -oE 'frame [0-9]+:|vk_dump: frame [0-9]+: [0-9]+ passes|FATAL.*|=== end' \
            | sed -E 's/^frame ([0-9]+):/frame \1\/1500 toward the dump/' >> "$out"
        pos=$n
    fi
    for d in $V/dump-*; do
        case "$seen" in *" $d "*) continue;; esac
        [ -f "$d/images.txt" ] || continue
        seen="$seen$d "
        p=$(grep -E '^pass [0-9]+: dispatch 8x9x12' "$d/passes.txt" | head -1 | awk '{print $2}' | tr -d :)
        nan=$(grep -E "^pass_${p}_img1" "$d/images.txt" | grep -oE 'nan [0-9]+' | head -1)
        echo "result $(basename "$d"): fog injection ${nan:-nan ?} (0 = fixed)" >> "$out"
        # the run's finished frame, kept current for an Emacs buffer (auto-revert)
        png=$(ls "$d"/*_t0_2560x1440_43_rgba8srgb.png 2>/dev/null | tail -1)
        [ -n "$png" ] && nix shell nixpkgs#imagemagick -c magick "$png" -resize 1280x720 \
            -gravity south -background black -fill white -splice 0x28 -annotate +0+4 "$(basename "$d")  ${nan:-}" \
            "$frame.tmp.png" && mv -f "$frame.tmp.png" "$frame"
    done
    sleep 2
done
