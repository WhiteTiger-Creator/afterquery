#!/usr/bin/env bash
# Rebuild a PGN archive.
#
#   decompress.sh <out_dir> <output.pgn>
#
# The result must match the original input byte for byte. Nothing may be read from the
# original file — only from <out_dir> and from code shipped under /app.
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "usage: decompress.sh <out_dir> <output.pgn>" >&2
    exit 2
fi

cd /app
exec python3 -m pgnpack decompress "$1" "$2"
