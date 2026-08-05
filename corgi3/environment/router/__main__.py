"""Answer a batch of queries: ``python -m router <graph> <queries> <output>``."""

from __future__ import annotations

import sys
import time

from .dijkstra import answer
from .graph import load, read_queries


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3:
        print("usage: python -m router <graph> <queries> <output>", file=sys.stderr)
        return 2
    graph_path, query_path, out_path = argv

    started = time.time()
    graph = load(graph_path)
    queries = read_queries(query_path)
    loaded = time.time() - started

    started = time.time()
    distances = answer(graph, queries)
    solved = time.time() - started

    with open(out_path, "w") as fh:
        for d in distances:
            fh.write(f"{int(d)}\n")

    print(f"{len(queries)} queries: load {loaded:.1f}s, solve {solved:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
