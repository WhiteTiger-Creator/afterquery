#!/usr/bin/env bash
# Predict the property for every molecule in a csv.
#
#   predict.sh <input.csv> <output.csv>
#
# The input has a `smiles` column and no measured values. The output must have one row per
# input row, in the same order, with columns `smiles,gap`. This is the only thing run when
# the work is scored.
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "usage: predict.sh <input.csv> <output.csv>" >&2
    exit 2
fi

cd /app
exec python3 -m molprop predict "$1" "$2"
