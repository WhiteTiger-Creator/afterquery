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
from fast import solve_batch

d = np.load("/app/model/graph.npz")
start, head, weight, n = d["start"], d["head"], d["weight"], int(d["n"])

src, dst = [], []
with open(sys.argv[2]) as fh:
    for line in fh:
        line = line.strip()
        if line:
            a, b = line.split()
            src.append(int(a) - 1)
            dst.append(int(b) - 1)

out = solve_batch(start, head, weight,
                  np.asarray(src, dtype=np.int32),
                  np.asarray(dst, dtype=np.int32), n)
with open(sys.argv[3], "w") as fh:
    for v in out:
        fh.write(f"{int(v)}\n")
' "$1" "$2" "$3"
SH

chmod +x /app/prepare.sh /app/solve.sh

echo "[solve] preparing"
/app/prepare.sh /app/data/road.gr.gz

echo "[solve] checking against the development queries"
/app/selfcheck.sh || true

echo "[solve] done"
