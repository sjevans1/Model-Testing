#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec python3 server.py "${1:-8100}"
