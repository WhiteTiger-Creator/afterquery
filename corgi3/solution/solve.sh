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
# Expected result: every answer identical to the shipped router, and a ratio of roughly
# 13-14x against it, which scores about 7.3 under 0.5 + 0.5 * ratio. A materially different
# number means the scoring pipeline is not doing what it is supposed to.
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
from fast import ball_batch, kth_batch, solve_batch, sweep_batch

d = np.load("/app/model/graph.npz")
start, head, weight, n = d["start"], d["head"], d["weight"], int(d["n"])
rstart, rhead, rweight = d["rstart"], d["rhead"], d["rweight"]

kinds, psrc, pdst, ssrc, bsrc, brad = [], [], [], [], [], []
rtgt, ksrc, kval = [], [], []
with open(sys.argv[2]) as fh:
    for line in fh:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "S":
            kinds.append("S"); ssrc.append(int(parts[1]) - 1)
        elif parts[0] == "B":
            kinds.append("B"); bsrc.append(int(parts[1]) - 1); brad.append(int(parts[2]))
        elif parts[0] == "R":
            kinds.append("R"); rtgt.append(int(parts[1]) - 1)
        elif parts[0] == "K":
            kinds.append("K"); ksrc.append(int(parts[1]) - 1); kval.append(int(parts[2]))
        else:
            kinds.append("P"); psrc.append(int(parts[1]) - 1); pdst.append(int(parts[2]) - 1)

point = solve_batch(start, head, weight,
                    np.asarray(psrc, dtype=np.int32),
                    np.asarray(pdst, dtype=np.int32), n) if psrc else []
swept = sweep_batch(start, head, weight,
                    np.asarray(ssrc, dtype=np.int32), n) if ssrc else []
balls = ball_batch(start, head, weight,
                   np.asarray(bsrc, dtype=np.int32),
                   np.asarray(brad, dtype=np.int64), n) if bsrc else []
revs  = sweep_batch(rstart, rhead, rweight,
                    np.asarray(rtgt, dtype=np.int32), n) if rtgt else []
kths  = kth_batch(start, head, weight,
                  np.asarray(ksrc, dtype=np.int32),
                  np.asarray(kval, dtype=np.int64), n) if ksrc else []

pi = si = bi = ri = ki = 0
with open(sys.argv[3], "w") as fh:
    for k in kinds:
        if k == "S":
            fh.write(f"{int(swept[si])}\n"); si += 1
        elif k == "B":
            fh.write(f"{int(balls[bi])}\n"); bi += 1
        elif k == "R":
            fh.write(f"{int(revs[ri])}\n"); ri += 1
        elif k == "K":
            fh.write(f"{int(kths[ki])}\n"); ki += 1
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
