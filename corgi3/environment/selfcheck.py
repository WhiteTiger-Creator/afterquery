"""Local check: are the answers still right, and how much faster is it?

Runs the shipped implementation and yours alternately over the development queries and
compares medians, which is the same method the real measurement uses. Interleaving matters
more than it looks: run one after the other and whatever else the machine is doing lands
entirely on whichever went second.

The development queries are fewer than the graded ones, so treat the ratio as a direction
rather than a promise — but a change that does not help here will not help there.
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP = Path("/app")
GRAPH = APP / "data" / "road.gr.gz"
DEV = APP / "data" / "queries.dev.txt"
PRISTINE = APP / ".reference"


def run(cmd, cwd=None, env=None):
    started = time.perf_counter()
    proc = subprocess.run(
        [str(c) for c in cmd], capture_output=True, text=True, cwd=cwd, env=env
    )
    return proc, time.perf_counter() - started


def read(path):
    try:
        return [x.strip() for x in Path(path).read_text().splitlines() if x.strip()]
    except OSError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default=str(DEV))
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    if not PRISTINE.is_dir():
        print(f"reference copy missing at {PRISTINE}", file=sys.stderr)
        return 2

    work = Path(tempfile.mkdtemp(prefix="selfcheck-"))
    env = dict(__import__("os").environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        base_times, cand_times = [], []
        reference = None
        for i in range(args.rounds):
            out = work / f"base_{i}.txt"
            proc, seconds = run(
                [sys.executable, "-m", "router", GRAPH, args.queries, out],
                cwd=str(PRISTINE),
                env=dict(env, PYTHONPATH=str(PRISTINE)),
            )
            if proc.returncode != 0:
                print("the reference implementation failed:", proc.stderr[-800:], file=sys.stderr)
                return 1
            base_times.append(seconds)
            reference = reference or read(out)

            out = work / f"cand_{i}.txt"
            proc, seconds = run([APP / "solve.sh", GRAPH, args.queries, out], cwd="/app", env=env)
            if proc.returncode != 0:
                print("solve.sh failed:", (proc.stdout + proc.stderr)[-800:], file=sys.stderr)
                return 1
            cand_times.append(seconds)

            given = read(out)
            if given is None:
                print("solve.sh produced no readable output", file=sys.stderr)
                return 1
            if len(given) != len(reference):
                print(f"  ANSWER COUNT MISMATCH {len(given)} vs {len(reference)} — scores zero")
                return 1
            if given != reference:
                bad = next(i for i, (a, b) in enumerate(zip(given, reference)) if a != b)
                print(f"  WRONG DISTANCE at query {bad + 1}: {given[bad]} vs {reference[bad]}")
                print("  scores zero — correctness gates everything")
                return 1

        base = statistics.median(base_times)
        cand = statistics.median(cand_times)
        ratio = base / cand if cand > 0 else 0.0
        reward = 0.5 + 0.5 * ratio

        print(f"queries        {len(reference):,}")
        print(f"  answers      all correct")
        print(f"  reference    {base:7.2f}s  median of {[round(x,2) for x in base_times]}")
        print(f"  yours        {cand:7.2f}s  median of {[round(x,2) for x in cand_times]}")
        print()
        print(f"  ratio        {ratio:.2f}x")
        print(f"  estimate     {reward:.3f}")
        print()
        print("  The graded queries are a larger set on the same network. Fixed costs you pay")
        print("  once — reading the graph, loading tables — matter less there than here.")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
