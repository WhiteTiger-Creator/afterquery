#!/usr/bin/env bash
# Reference solution.
#
# Two changes, both of which leave every distance exactly as it was.
#
#   1. The inner loop is compiled. It is the same Dijkstra with the same binary heap and
#      the same settling order — but a relaxation becomes a few machine instructions
#      instead of a bytecode dispatch, a tuple allocation and a dict lookup.
#
#   2. The graph is parsed once, in preparation, and cached as typed arrays. The shipped
#      router re-reads a gzipped text file on every single run.
#
# Preparation never sees the queries, which is the point: both of these serve any query.
set -euo pipefail

SOLUTION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[solve] installing the reference router"
rm -rf /app/altrouter
cp -r "$SOLUTION_DIR/altrouter" /app/altrouter

cat > /app/prepare.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then
    echo "usage: prepare.sh <graph>" >&2
    exit 2
fi
cd /app
python3 -c '
import sys
sys.path.insert(0, "/app/altrouter")
from altrouter.build import compile_extension, cache_graph
compile_extension()
print("compiled the router extension")
print("graph cached ->", cache_graph(sys.argv[1]))
' "$1"
SH

cat > /app/solve.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 3 ]; then
    echo "usage: solve.sh <graph> <queries> <output>" >&2
    exit 2
fi
cd /app
exec python3 -c '
import sys
import numpy as np
sys.path.insert(0, "/app/altrouter")
from fast import solve_batch, sweep_batch

d = np.load("/app/model/graph.npz")
start, head, weight, n = d["start"], d["head"], d["weight"], int(d["n"])

kinds, psrc, pdst, ssrc = [], [], [], []
with open(sys.argv[2]) as fh:
    for line in fh:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "S":
            kinds.append("S"); ssrc.append(int(parts[1]) - 1)
        else:
            kinds.append("P"); psrc.append(int(parts[1]) - 1); pdst.append(int(parts[2]) - 1)

point = solve_batch(start, head, weight,
                    np.asarray(psrc, dtype=np.int32),
                    np.asarray(pdst, dtype=np.int32), n) if psrc else []
swept = sweep_batch(start, head, weight,
                    np.asarray(ssrc, dtype=np.int32), n) if ssrc else []

pi = si = 0
with open(sys.argv[3], "w") as fh:
    for k in kinds:
        if k == "S":
            fh.write(f"{int(swept[si])}\n"); si += 1
        else:
            fh.write(f"{int(point[pi])}\n"); pi += 1
' "$1" "$2" "$3"
SH

chmod +x /app/prepare.sh /app/solve.sh

echo "[solve] preparing"
/app/prepare.sh /app/data/road.gr.gz

echo "[solve] checking against the development queries"
/app/selfcheck.sh || true

echo "[solve] done"
