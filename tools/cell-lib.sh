# sourced by ab-cell, load-cell, suite-run (ARCHITECTURE.md 11): load-average gate, the run's cell.txt (cache warm/cold,
# scenario recipe hash, load before/after; results-add reads it), and the nightly's one redo of a run the host disturbed.
LOAD_MAX=${LOAD_MAX:-6}
# wait for a 1-minute load average under LOAD_MAX (no measurement beside a build, 2026-11-12)
cell_wait() { while [ "$(awk -v m=$LOAD_MAX '{print ($1 < m)}' /proc/loadavg)" != 1 ]; do sleep 20; done; cut -d' ' -f1 /proc/loadavg; }
# warm when the shader cache dir has files and the pipeline cache file is not empty, at the run's start
cell_cache() { [ -n "$(ls -A "$1" 2>/dev/null | head -1)" ] && [ -s "$2" ] && echo warm || echo cold; }
# cell_note <run name> <cache> <recipe hash> <load before>: write .lab/<name>/cell.txt after the run
cell_note() { printf 'cache=%s\nrecipe=%s\nload_before=%s\nload_after=%s\n' "$2" "$3" "$4" "$(cut -d' ' -f1 /proc/loadavg)" > "$R/.lab/$1/cell.txt" 2>/dev/null; }
# cell_redo <run name>: true once when CELL_REDO is set (tools/nightly) and the load rose above LOAD_MAX + 2 during the run
# (the game itself makes about 3-5)
cell_redo() {
  [ -n "$CELL_REDO" ] || return 1
  [ -e "$R/.lab/$1.redone" ] && { rm -f "$R/.lab/$1.redone"; return 1; }
  awk -F= -v m=$LOAD_MAX '$1 == "load_after" { exit !($2 > m + 2) }' "$R/.lab/$1/cell.txt" 2>/dev/null || return 1
  touch "$R/.lab/$1.redone"; echo "$1: load average above $((LOAD_MAX + 2)) after the run: redo once" >&2
}
# cell_scenario <name>: sets w (warp-save args), rdbg (DBG_TEST recipe commands), rhash, LAB_PROFILE_SRC from
# tools/scenarios/<name>.dbg when SCENARIO_RECIPES=1 (tools/suite sets it); else leaves the old live-profile copy
cell_scenario() {
  rdbg= rhash=
  [ "${SCENARIO_RECIPES:-0}" = 1 ] && [ -f $R/tools/scenarios/$1.dbg ] || return 0
  w=$($R/tools/recipe $1 warp) rdbg=$($R/tools/recipe $1 dbg) rhash=$($R/tools/recipe $1 hash)
  # recipe v1 (a mark's recipe kept as a scenario): its game data lines go into the save too (tools/warp-save gd=)
  [ "$($R/tools/recipe $1 version)" -ge 1 ] && w="$w gd=$R/tools/scenarios/$1.dbg"
  export LAB_PROFILE_SRC=$($R/tools/recipe $1 base)
}
# cell_xlate <exe>: the translator the build was made for (builds.tsv xlate column dir), e.g. play41 -> xlate-play33
cell_xlate() { local d; d=$(awk -F'\t' -v e=$1 '$1 == e { split($4, a, "/"); print a[1] }' $R/builds.tsv)
  # builds.tsv names translators under build/v111/ (xlate-play33) or build/ (xlate-701e7ce): before 2026-11-15 the
  # second kind fell back to xlate-rebase (32768 pool) without a word
  local t; for t in $R/NX2navi/build/v111/$d $R/NX2navi/build/$d; do [ -n "$d" ] && [ -x $t/nx2navi_xlate ] && { echo $t/nx2navi_xlate; return; }; done
  echo "cell_xlate: no translator for $1 ('$d'), using xlate-rebase" >&2; echo $R/NX2navi/build/v111/xlate-rebase/nx2navi_xlate; }
