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


def ball_count(graph: Graph, source: int, radius: int) -> int:
    """How many nodes lie within `radius` of `source`.

    A third shape again. There is no target to steer towards, so goal-directed tricks are
    useless — but unlike a sweep the search stops early, and most of the network is never
    touched. What makes this fast is knowing when to stop expanding, not where to go.
    """
    start = graph.start
    head = graph.head
    weight = graph.weight

    dist = {source: 0}
    heap = [(0, source)]
    reached = 0

    while heap:
        d, u = heappop(heap)
        if d > dist.get(u, INF):
            continue
        reached += 1
        for i in range(start[u], start[u + 1]):
            v = head[i]
            nd = d + weight[i]
            if nd <= radius and nd < dist.get(v, INF):
                dist[v] = nd
                heappush(heap, (nd, v))
    return reached


def reverse_sweep_total(graph: Graph, target: int, reverse: Graph) -> int:
    """The sum of distances *into* `target` from everything that can reach it.

    A fourth shape. Everything above searches outwards from a source; this one searches
    backwards from a destination, which needs the arcs turned around. A structure built for
    forward search does not answer it, and building the reverse takes memory of its own.
    """
    return sweep_total(reverse, target)


def kth_nearest(graph: Graph, source: int, k: int) -> int:
    """The distance to the k-th closest node, counting the source itself as the first.

    A fifth shape, and the pruning is different again: there is no radius to stop at and no
    target to aim for, only a count. The search ends when enough nodes have been settled,
    so what matters is settling them in the cheapest possible order and stopping dead.
    """
    start = graph.start
    head = graph.head
    weight = graph.weight

    dist = {source: 0}
    heap = [(0, source)]
    settled = 0

    while heap:
        d, u = heappop(heap)
        if d > dist.get(u, INF):
            continue
        settled += 1
        if settled >= k:
            return d
        for i in range(start[u], start[u + 1]):
            v = head[i]
            nd = d + weight[i]
            if nd < dist.get(v, INF):
                dist[v] = nd
                heappush(heap, (nd, v))
    return -1


def answer(graph: Graph, queries) -> list[int]:
    """Answer a batch of queries in order.

    A query is one of ``("P", source, target)``, ``("S", source)``, ``("B", source, radius)``,
    ``("R", target)`` — the sum of distances *into* a node — or ``("K", source, k)`` — the
    distance to the k-th closest node.
    """
    reverse = None
    out = []
    for query in queries:
        if query[0] == "S":
            out.append(sweep_total(graph, query[1]))
        elif query[0] == "B":
            out.append(ball_count(graph, query[1], query[2]))
        elif query[0] == "R":
            if reverse is None:
                reverse = graph.reversed()
            out.append(reverse_sweep_total(graph, query[1], reverse))
        elif query[0] == "K":
            out.append(kth_nearest(graph, query[1], query[2]))
        else:
            d = shortest_path(graph, query[1], query[2])
            out.append(-1 if d == INF else int(d))
    return out
