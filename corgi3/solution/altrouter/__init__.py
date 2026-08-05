"""altrouter — the reference answer: A* with landmark bounds."""

from __future__ import annotations

from .alt import answer, build, load_tables, shortest_path

__all__ = ["answer", "build", "load_tables", "shortest_path"]
