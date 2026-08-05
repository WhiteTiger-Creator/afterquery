#!/usr/bin/env bash
# Answer shortest-path queries.
#
#   solve.sh <graph.gr.gz> <queries.txt> <output.txt>
#
# One line of output per query line, in the same order: the exact shortest-path distance,
# or -1 if the target cannot be reached. This is the only thing that is timed.
set -euo pipefail

if [ "$#" -ne 3 ]; then
    echo "usage: solve.sh <graph> <queries> <output>" >&2
    exit 2
fi

cd /app
exec python3 -m router "$1" "$2" "$3"
