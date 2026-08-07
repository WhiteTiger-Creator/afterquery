"""Reading the road network.

The file is the standard DIMACS shortest-path format: a `p sp N M` line giving the number
of nodes and arcs, then one `a tail head weight` line per directed arc. Weights are travel
distances and are positive integers, so the graph is exactly what Dijkstra was written for.

The graph is held as a compressed sparse row: arcs sorted by tail, with an index saying
where each node's arcs begin. That is the layout every later idea wants — the arcs leaving
a node are contiguous, so walking them is a straight scan.
"""

from __future__ import annotations

import gzip
from pathlib import Path


class Graph:
    """A directed, positively weighted graph in compressed sparse row form."""

    __slots__ = ("n", "start", "head", "weight")

    def __init__(self, n: int, start: list[int], head: list[int], weight: list[int]) -> None:
        self.n = n
        self.start = start
        self.head = head
        self.weight = weight

    @property
    def m(self) -> int:
        return len(self.head)

    def arcs(self, node: int):
        """The arcs leaving `node`, as (head, weight) pairs."""
        for i in range(self.start[node], self.start[node + 1]):
            yield self.head[i], self.weight[i]

    def reversed(self) -> "Graph":
        """The same graph with every arc turned around."""
        counts = [0] * (self.n + 1)
        for v in self.head:
            counts[v + 1] += 1
        for i in range(self.n):
            counts[i + 1] += counts[i]
        start = list(counts)
        head = [0] * len(self.head)
        weight = [0] * len(self.head)
        cursor = list(counts[:-1])
        for u in range(self.n):
            for i in range(self.start[u], self.start[u + 1]):
                p = cursor[self.head[i]]
                head[p] = u
                weight[p] = self.weight[i]
                cursor[self.head[i]] = p + 1
        return Graph(self.n, start, head, weight)


def load(path: str | Path) -> Graph:
    """Read a DIMACS .gr file, gzipped or not."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    tails: list[int] = []
    heads: list[int] = []
    weights: list[int] = []
    n = 0
    with opener(path, "rt") as fh:
        for line in fh:
            kind = line[0]
            if kind == "a":
                _, u, v, w = line.split()
                tails.append(int(u) - 1)
                heads.append(int(v) - 1)
                weights.append(int(w))
            elif kind == "p":
                n = int(line.split()[2])

    counts = [0] * (n + 1)
    for u in tails:
        counts[u + 1] += 1
    for i in range(n):
        counts[i + 1] += counts[i]
    start = list(counts)
    head = [0] * len(heads)
    weight = [0] * len(heads)
    cursor = list(counts[:-1])
    for u, v, w in zip(tails, heads, weights):
        p = cursor[u]
        head[p] = v
        weight[p] = w
        cursor[u] = p + 1
    return Graph(n, start, head, weight)


def read_queries(path: str | Path):
    """One query per line, one-based as in the graph file.

        P <source> <target>     the distance from source to target
        S <source>              the sum of distances from source to all it reaches
        B <source> <radius>     how many nodes lie within radius of source
        R <target>              the sum of distances into target from all that reach it
        K <source> <k>          the distance to the k-th closest node
    """
    out = []
    with open(path) as fh:
        for line in fh:
            parts = line.split()
            if not parts:
                continue
            kind = parts[0]
            if kind == "S":
                out.append(("S", int(parts[1]) - 1))
            elif kind == "B":
                out.append(("B", int(parts[1]) - 1, int(parts[2])))
            elif kind == "R":
                out.append(("R", int(parts[1]) - 1))
            elif kind == "K":
                out.append(("K", int(parts[1]) - 1, int(parts[2])))
            else:
                out.append(("P", int(parts[1]) - 1, int(parts[2]) - 1))
    return out
