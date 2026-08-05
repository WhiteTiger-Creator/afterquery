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


def sweep_total(graph: Graph, source: int) -> int:
    """The sum of the distances from `source` to every node it can reach.

    A different shape of question from a point-to-point query, and a different problem to
    make fast: there is no target to aim at, so nothing that prunes the search towards one
    helps at all. The whole reachable network has to be settled either way.
    """
    start = graph.start
    head = graph.head
    weight = graph.weight

    dist = [INF] * graph.n
    dist[source] = 0
    heap = [(0, source)]
    total = 0

    while heap:
        d, u = heappop(heap)
        if d > dist[u]:
            continue
        total += d
        for i in range(start[u], start[u + 1]):
            v = head[i]
            nd = d + weight[i]
            if nd < dist[v]:
                dist[v] = nd
                heappush(heap, (nd, v))
    return total


def answer(graph: Graph, queries) -> list[int]:
    """Answer a batch of queries in order.

    Each query is either ``("P", source, target)`` — the distance between two nodes — or
    ``("S", source)`` — the sum of distances from one node to everything it reaches.
    """
    out = []
    for query in queries:
        if query[0] == "S":
            out.append(sweep_total(graph, query[1]))
        else:
            d = shortest_path(graph, query[1], query[2])
            out.append(-1 if d == INF else int(d))
    return out
