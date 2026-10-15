#!/bin/sh
set -eu
cd "$(dirname "$0")"
PYTHONPATH=src python3 -m adminaccess.app
