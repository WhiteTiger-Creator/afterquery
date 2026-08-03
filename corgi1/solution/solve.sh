#!/usr/bin/env bash
# Reference solution.
#
# Two changes to the shipped archiver, both aimed at the two places it wastes space.
#
#   1. Move coding. Instead of treating every legal move as equally likely, fit a
#      conditional model over the legal move set and drive the range coder with its
#      probabilities. Training minimises negative log-likelihood, which is the same
#      quantity the archive pays in bits, so the training curve is a size forecast.
#
#   2. Header coding. Split the header block into columns and give each field a transform
#      that suits it — packed identifiers, delta-coded times, offset-coded ratings,
#      opening names predicted from their code — instead of one undifferentiated blob.
#
# The trained weights are quantised to int16 and stored compressed, because the model is
# part of what has to be transmitted.
set -euo pipefail

SOLUTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d /tmp/solve-XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

echo "[solve] installing the reference codec"
rm -rf /app/refpack
cp -r "$SOLUTION_DIR/refpack" /app/refpack

echo "[solve] training the move model on the local corpus"
cd /app
python3 -m refpack.train \
    --corpus /app/corpus/train.pgn \
    --out "$WORK/weights.npz" \
    --games 22000 \
    --epochs 30

echo "[solve] compressing the model"
xz -9e -c "$WORK/weights.npz" > /app/refpack/weights.npz.xz
ls -l /app/refpack/weights.npz.xz

# Everything left under /app counts toward the archive's size, including source. The
# trainer has done its job and is not needed to unpack anything, so it goes.
rm -f /app/refpack/train.py
find /app/refpack -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

echo "[solve] rewiring the interface"
cat > /app/compress.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 2 ]; then
    echo "usage: compress.sh <input.pgn> <out_dir>" >&2
    exit 2
fi
cd /app
exec python3 -c '
import sys
from refpack import codec
codec.compress(sys.argv[1], sys.argv[2], "/app/refpack/weights.npz.xz")
' "$1" "$2"
SH

cat > /app/decompress.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 2 ]; then
    echo "usage: decompress.sh <out_dir> <output.pgn>" >&2
    exit 2
fi
cd /app
exec python3 -c '
import sys
from refpack import codec
codec.decompress(sys.argv[1], sys.argv[2], "/app/refpack/weights.npz.xz")
' "$1" "$2"
SH

chmod +x /app/compress.sh /app/decompress.sh

echo "[solve] verifying on the local holdout"
/app/selfcheck.sh || true

echo "[solve] done"
