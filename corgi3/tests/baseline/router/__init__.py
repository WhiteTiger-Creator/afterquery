"""router — shortest-path queries on a road network."""

from __future__ import annotations

from .dijkstra import answer, shortest_path
from .graph import Graph, load, read_queries

__all__ = ["Graph", "answer", "load", "read_queries", "shortest_path"]
