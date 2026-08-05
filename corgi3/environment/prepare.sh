#!/usr/bin/env bash
# Optional: do any one-off work on the graph before queries arrive.
#
#   prepare.sh <graph.gr.gz>
#
# This runs once, is not timed, and may write whatever it likes under /app. The shipped
# implementation has nothing to prepare, so it does nothing.
#
# It does not see the queries. Whatever it builds has to be useful for any of them.
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "usage: prepare.sh <graph>" >&2
    exit 2
fi

echo "nothing to prepare"
