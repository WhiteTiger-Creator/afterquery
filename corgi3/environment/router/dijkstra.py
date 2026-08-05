"""Shortest paths, the straightforward way.

Dijkstra with a binary heap. It is correct, it is not fast, and the reason it is not fast
is worth stating plainly: it has no idea where the target is. Asked for a route across the
city it will happily settle every node in the opposite direction first, because nothing in
the algorithm distinguishes "closer to the destination" from "closer to the source".

Everything that makes shortest-path queries quick on a road network is a way of fixing
that, and none of it changes a single answer.
"""

from __future__ import annotations

from heapq import heappop, heappush

from .graph import Graph

INF = float("inf")


def shortest_path(graph: Graph, source: int, target: int) -> float:
    """The distance from `source` to `target`, or infinity if unreachable."""
    if source == target:
        return 0

    start = graph.start
    head = graph.head
    weight = graph.weight

    dist = [INF] * graph.n
    dist[source] = 0
    heap = [(0, source)]

    while heap:
        d, u = heappop(heap)
        if d > dist[u]:
            continue
        if u == target:
            return d
        for i in range(start[u], start[u + 1]):
            v = head[i]
            nd = d + weight[i]
            if nd < dist[v]:
                dist[v] = nd
                heappush(heap, (nd, v))
    return INF


def answer(graph: Graph, queries) -> list[float]:
    """Answer a batch of queries in order."""
    return [shortest_path(graph, s, t) for s, t in queries]
