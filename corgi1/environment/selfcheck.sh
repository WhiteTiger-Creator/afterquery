#!/usr/bin/env bash
# Round-trip and score estimate against the local holdout.
#
#   ./selfcheck.sh                 # use corpus/holdout.pgn
#   ./selfcheck.sh --input FILE    # use some other PGN
set -euo pipefail
cd /app
exec python3 /app/selfcheck.py "$@"
