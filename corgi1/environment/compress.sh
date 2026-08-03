#!/usr/bin/env bash
# Pack a PGN archive.
#
#   compress.sh <input.pgn> <out_dir>
#
# Everything needed to rebuild the input must end up inside <out_dir>. The total size of
# that directory is what gets measured, so a model or dictionary written there is part of
# the cost, not a way around it.
#
# Replace the body freely; only the two arguments and that guarantee are fixed.
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "usage: compress.sh <input.pgn> <out_dir>" >&2
    exit 2
fi

cd /app
exec python3 -m pgnpack compress "$1" "$2"
