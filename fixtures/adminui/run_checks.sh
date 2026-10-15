#!/bin/sh
# Runs the tests you add under tests/ (python unittest and/or node scripts).
set -eu
cd "$(dirname "$0")"
if [ -d tests ] && [ -n "$(find tests -name 'test_*.py' -print -quit 2>/dev/null)" ]; then
  python3 -m unittest discover -s tests -v
fi
for script in tests/*.mjs tests/*.js; do
  [ -e "$script" ] || continue
  case "$script" in
    tests/*.mjs|tests/*.js) node "$script" ;;
  esac
done
echo "run_checks.sh: done"
