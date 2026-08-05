"""A* guided by landmark lower bounds.

Dijkstra explores in every direction because nothing tells it which way the target lies.
A* fixes that if you can supply a lower bound on the remaining distance that is never an
overestimate — an admissible one — because then the first time the target comes off the
heap its distance is already final. Answers do not change; only the order of exploration
does, and how much of the map gets touched on the way.

The bound comes from landmarks. Precompute, for a handful of well-spread nodes L, the
distance from L to everything and from everything to L. Then for any node v and target t
the triangle inequality gives two bounds:

    d(v, t) >= d(L, t) - d(L, v)        and        d(v, t) >= d(v, L) - d(t, L)

Take the largest over all landmarks. Each is valid on its own, so the maximum is valid too,
and picking landmarks far apart makes at least one of them tight for most queries.

The landmarks are chosen by farthest-point selection: start somewhere, and repeatedly take
whatever node is furthest from the last one picked. That spreads them around the edges of
the network, which is where they do the most good.
"""

from __future__ import annotations

import pickle
import random
from heapq import heappop, heappush
from pathlib import Path

from router.graph import Graph

INF = float("inf")
LANDMARK_FILE = Path("/app/model/landmarks.pkl")
LANDMARKS = 16


def full_sweep(graph: Graph, source: int) -> list:
    """Distance from `source` to every node."""
    start, head, weight = graph.start, graph.head, graph.weight
    dist = [INF] * graph.n
    dist[source] = 0
    heap = [(0, source)]
    while heap:
        d, u = heappop(heap)
        if d > dist[u]:
            continue
        for i in range(start[u], start[u + 1]):
            v = head[i]
            nd = d + weight[i]
            if nd < dist[v]:
                dist[v] = nd
                heappush(heap, (nd, v))
    return dist


def choose_landmarks(graph: Graph, count: int, seed: int = 5) -> list[int]:
    rng = random.Random(seed)
    current = rng.randrange(graph.n)
    chosen = []
    for _ in range(count):
        away = full_sweep(graph, current)
        best, best_node = -1.0, current
        for node, d in enumerate(away):
            if d != INF and d > best:
                best, best_node = d, node
        current = best_node
        chosen.append(current)
    return chosen


def build(graph: Graph, path: Path = LANDMARK_FILE, count: int = LANDMARKS) -> Path:
    """Precompute the landmark tables and store them."""
    reverse = graph.reversed()
    marks = choose_landmarks(graph, count)
    outward = [full_sweep(graph, m) for m in marks]     # d(L, ·)
    inward = [full_sweep(reverse, m) for m in marks]    # d(·, L)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump({"marks": marks, "outward": outward, "inward": inward}, fh, protocol=4)
    return path


def load_tables(path: Path = LANDMARK_FILE):
    with open(path, "rb") as fh:
        tables = pickle.load(fh)
    return tables["outward"], tables["inward"]


def shortest_path(graph: Graph, source: int, target: int, outward, inward) -> float:
    """Exactly the distance Dijkstra would return, reached by touching far less of the map."""
    if source == target:
        return 0

    start, head, weight = graph.start, graph.head, graph.weight

    # Only landmarks that know about the target can bound anything.
    bounds = []
    for out, inn in zip(outward, inward):
        ot, it = out[target], inn[target]
        if ot != INF or it != INF:
            bounds.append((out, ot, inn, it))

    def estimate(v: int) -> float:
        best = 0
        for out, ot, inn, it in bounds:
            if ot != INF:
                ov = out[v]
                if ov != INF:
                    x = ot - ov
                    if x > best:
                        best = x
            if it != INF:
                iv = inn[v]
                if iv != INF:
                    x = iv - it
                    if x > best:
                        best = x
        return best

    dist = {source: 0}
    heap = [(estimate(source), 0, source)]
    settled = set()
    while heap:
        _priority, d, u = heappop(heap)
        if u in settled:
            continue
        if u == target:
            return d
        settled.add(u)
        for i in range(start[u], start[u + 1]):
            v = head[i]
            nd = d + weight[i]
            if nd < dist.get(v, INF):
                dist[v] = nd
                heappush(heap, (nd + estimate(v), nd, v))
    return INF


def answer(graph: Graph, queries, outward, inward) -> list[float]:
    return [shortest_path(graph, s, t, outward, inward) for s, t in queries]
