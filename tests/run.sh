#!/bin/bash
# Every test is self-contained: it builds a throwaway home, runs the real code against it, and
# prints PASS/FAIL. GUI tests need xvfb; they are skipped (not silently passed) without it.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/tests" || exit 1
GUI="test_osk.py test_navosk.py test_pcsd.py test_move_ui.py test_pcsteam2.py test_recent_backfill.py"
fail=0
for t in test_lastplay.py test_move.py test_compat.py; do
  out=$(python3 "$t" 2>&1); r=$?
  printf '  %-22s %s\n' "$t" "$(tail -1 <<<"$out")"; [ $r -ne 0 ] && fail=1
done
for t in $GUI; do
  if command -v xvfb-run >/dev/null 2>&1; then
    out=$(xvfb-run -a python3 "$t" 2>&1 | grep -v 'Gtk-WARNING\|GLib-GObject'); r=${PIPESTATUS[0]}
    printf '  %-22s %s\n' "$t" "$(tail -1 <<<"$out")"; [ $r -ne 0 ] && fail=1
  else
    printf '  %-22s SKIPPED (no xvfb-run)\n' "$t"
  fi
done
for t in test_pcsaves2.sh; do
  out=$(bash "$t" 2>&1); r=$?
  printf '  %-22s %s\n' "$t" "$(tail -1 <<<"$out")"; [ $r -ne 0 ] && fail=1
done
[ $fail -eq 0 ] && echo "  ALL PASS" || echo "  FAILURES"
exit $fail
