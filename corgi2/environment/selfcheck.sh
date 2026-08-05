#!/usr/bin/env bash
# Predict for the development molecules and report the error.
#
#   ./selfcheck.sh                 # use data/dev.csv
#   ./selfcheck.sh --input FILE    # use some other labelled csv
set -euo pipefail
cd /app
exec python3 /app/selfcheck.py "$@"
