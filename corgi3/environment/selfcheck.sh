#!/usr/bin/env bash
# Compare your router against the shipped one on the development queries.
#
#   ./selfcheck.sh                       # 60 development queries, 3 rounds each
#   ./selfcheck.sh --queries FILE        # some other query file
#   ./selfcheck.sh --rounds 5            # more repetitions, steadier medians
set -euo pipefail
cd /app
exec python3 /app/selfcheck.py "$@"
