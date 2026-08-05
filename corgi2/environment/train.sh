#!/usr/bin/env bash
# Fit a model on /app/data/train.csv and leave it somewhere predict.sh can find it.
#
#   train.sh
#
# Run this yourself whenever you change how the model is built. Only predict.sh is run
# when the work is scored, so whatever this produces has to be on disk by then.
set -euo pipefail
cd /app
exec python3 -m molprop train --data /app/data/train.csv
