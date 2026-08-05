#!/usr/bin/env bash
# Reference solution.
#
# Two changes to the shipped pipeline.
#
#   1. Read the molecule. SMILES is parsed into a graph and turned into counts of hashed
#      circular atom environments — which substructures are present rather than which
#      characters. Symbol counts cannot separate two molecules with the same formula and
#      different connectivity; the property can.
#
#   2. Blend the model. Gradient boosting is better on molecules resembling the training
#      set and worse off it, because trees cannot extrapolate past their leaves and every
#      graded molecule carries a ring system absent from training. A modest weight on ridge
#      regression degrades more gracefully.
#
# The hash used for the fingerprint is CRC32 rather than the builtin: Python salts string
# hashing per process, so the builtin would bin the same substructure differently at
# training and prediction time.
set -euo pipefail

SOLUTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[solve] installing the reference model"
rm -rf /app/refmodel
cp -r "$SOLUTION_DIR/refmodel" /app/refmodel

echo "[solve] fitting on the training molecules"
cd /app
python3 -c '
from refmodel.model import train
train("/app/data/train.csv")
'
ls -l /app/model

echo "[solve] rewiring the interface"
cat > /app/train.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cd /app
exec python3 -c '
from refmodel.model import train
train("/app/data/train.csv")
'
SH

cat > /app/predict.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 2 ]; then
    echo "usage: predict.sh <input.csv> <output.csv>" >&2
    exit 2
fi
cd /app
exec python3 -c '
import sys
from refmodel.model import predict
predict(sys.argv[1], sys.argv[2])
' "$1" "$2"
SH

chmod +x /app/train.sh /app/predict.sh

echo "[solve] checking against the development molecules"
/app/selfcheck.sh || true

echo "[solve] done"
