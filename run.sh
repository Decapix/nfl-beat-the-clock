#!/usr/bin/env bash
# macOS / Linux: one command -> deps, data, build, dashboard. The real work is in run.py.
set -e
cd "$(dirname "$0")"
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    exec "$c" run.py "$@"
  fi
done
echo "Python 3.10+ not found. Install it (macOS: brew install python, or python.org) and rerun." >&2
exit 1
