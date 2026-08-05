"""Score a submission.

Correctness first: every distance must equal what the shipped implementation produces, on
a set of queries the workspace has never seen. Nothing about being fast earns anything
until that holds, and a single wrong distance ends the run at zero.

Speed second, and measured carefully. The two implementations are run alternately, several
times each, and compared on medians. Interleaving them means whatever the machine is doing
during the run — another container, a noisy neighbour, thermal drift — lands on both sides
rather than on one, and the median discards the worst of what is left. The baseline is run
from this directory's own copy, so slowing the shipped code down changes nothing.

Preparation is untimed but bounded, and it never sees the queries: whatever it builds has
to be useful for any of them. Files written during a *timed* run are removed afterwards, so
the second repetition cannot read what the first one cached.
"""

from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
BASELINE = HERE / "baseline"
APP = Path("/app")

GRAPH = APP / "data" / "road.gr.gz"
QUERIES = DATA / "queries.graded.txt"
SCORING = DATA / "scoring.json"

REPORT_DIR = Path(os.environ.get("REWARD_DIR", "/logs/verifier"))

PREPARE_TIMEOUT = int(os.environ.get("PREPARE_TIMEOUT", "1800"))
SOLVE_TIMEOUT = int(os.environ.get("SOLVE_TIMEOUT", "900"))
ROUNDS = int(os.environ.get("TIMING_ROUNDS", "3"))


def write_report(payload: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    reward = float(payload["reward"])
    (REPORT_DIR / "reward.json").write_text(json.dumps(payload, indent=2, sort_keys=True))
    (REPORT_DIR / "reward.txt").write_text(f"{reward:.6f}\n")
    print(json.dumps(payload, indent=2, sort_keys=True))


def fail(reason: str, **extra) -> int:
    payload = {"reward": 0.0, "status": "failed", "reason": reason}
    payload.update(extra)
    write_report(payload)
    return 0


def run(cmd, timeout, cwd=None, env=None):
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            [str(c) for c in cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout}s", 0.0
    except OSError as exc:
        return None, f"could not run {cmd[0]}: {exc}", 0.0
    elapsed = time.perf_counter() - started
    if proc.returncode != 0:
        return None, f"exit {proc.returncode}: {(proc.stdout + proc.stderr)[-1500:]}", elapsed
    return proc, "", elapsed


def snapshot(root: Path) -> set:
    return {p for p in root.rglob("*") if p.is_file()}


def live_pids() -> set:
    return {int(p.name) for p in Path("/proc").iterdir() if p.name.isdigit()}


def ancestry(pid: int) -> list:
    chain = []
    for _ in range(64):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            break
        chain.append(ppid)
        if ppid <= 1:
            break
        pid = ppid
    return chain


def kill_new(before: set) -> int:
    """Stop anything a timed run left running.

    A process that survives the round could be holding the answers it just computed and
    handing them back on the next one, which would make the second and third rounds free.
    Preparation's own processes are started before the snapshot and are left alone.
    """
    import signal

    protected = {os.getpid(), 1} | set(ancestry(os.getpid()))
    killed = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in before or pid in protected:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            killed += 1
        except OSError:
            pass
    return killed


def scrub(root: Path, before: set) -> int:
    """Remove files created since the snapshot, so a cached answer cannot be reused."""
    removed = 0
    for path in root.rglob("*"):
        if path.is_file() and path not in before:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def read_answers(path: Path) -> list[str] | None:
    try:
        return [line.strip() for line in path.read_text().splitlines() if line.strip() != ""]
    except OSError:
        return None


def main() -> int:
    for required in (QUERIES, SCORING):
        if not required.is_file():
            return fail(f"verifier data missing: {required.name}")
    if not GRAPH.is_file():
        return fail("the road network is missing from /app/data")

    scoring = json.loads(SCORING.read_text())
    solve_sh = APP / "solve.sh"
    if not solve_sh.is_file() or not os.access(solve_sh, os.X_OK):
        return fail("/app/solve.sh is missing or not executable")

    n_queries = len([q for q in QUERIES.read_text().splitlines() if q.strip()])
    work = Path(tempfile.mkdtemp(prefix="grade-", dir="/tmp"))
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

    try:
        # ---------------------------------------------------------- preparation
        prepare_sh = APP / "prepare.sh"
        prepare_seconds = 0.0
        if prepare_sh.is_file() and os.access(prepare_sh, os.X_OK):
            proc, why, prepare_seconds = run(
                [prepare_sh, GRAPH], PREPARE_TIMEOUT, cwd="/app", env=env
            )
            if proc is None:
                return fail(f"prepare.sh failed — {why}")

        # Anything from here on that a timed run creates gets removed between rounds, and
        # anything it leaves running gets stopped.
        after_prepare = snapshot(APP)
        pids_after_prepare = live_pids()
        stopped = 0

        # ---------------------------------------------------------- timed rounds
        base_times: list[float] = []
        cand_times: list[float] = []
        reference: list[str] | None = None

        for round_index in range(ROUNDS):
            base_out = work / f"base_{round_index}.txt"
            proc, why, seconds = run(
                [sys.executable, "-m", "router", GRAPH, QUERIES, base_out],
                SOLVE_TIMEOUT,
                cwd=str(BASELINE),
                env=dict(env, PYTHONPATH=str(BASELINE)),
            )
            if proc is None:
                return fail(f"the reference implementation failed — {why}")
            base_times.append(seconds)
            answers = read_answers(base_out)
            if reference is None:
                reference = answers
            elif answers != reference:
                return fail("the reference implementation was not reproducible")

            cand_out = work / f"cand_{round_index}.txt"
            proc, why, seconds = run(
                [solve_sh, GRAPH, QUERIES, cand_out], SOLVE_TIMEOUT, cwd="/app", env=env
            )
            if proc is None:
                return fail(f"solve.sh failed — {why}")
            cand_times.append(seconds)

            given = read_answers(cand_out)
            if given is None:
                return fail("solve.sh produced no readable output")
            if len(given) != n_queries:
                return fail(
                    "one distance per query is required",
                    expected=n_queries,
                    received=len(given),
                )
            if given != reference:
                wrong = next(
                    (i for i, (a, b) in enumerate(zip(given, reference)) if a != b), None
                )
                return fail(
                    "a distance does not match the reference",
                    first_wrong_query=(wrong or 0) + 1,
                )

            scrub(APP, after_prepare)
            stopped += kill_new(pids_after_prepare)

        base = statistics.median(base_times)
        cand = statistics.median(cand_times)
        if cand <= 0:
            return fail("measured time was zero, which cannot be right")

        ratio = base / cand
        speedup = max(0.0, ratio - 1.0)
        reward = 0.5 + 0.5 * speedup

        write_report(
            {
                "reward": round(reward, 6),
                "status": "scored",
                "correct": True,
                "ratio": round(ratio, 4),
                "speedup_term": round(speedup, 4),
                "baseline_seconds": [round(x, 3) for x in base_times],
                "candidate_seconds": [round(x, 3) for x in cand_times],
                "baseline_median": round(base, 3),
                "candidate_median": round(cand, 3),
                "prepare_seconds": round(prepare_seconds, 1),
                "queries": n_queries,
                "rounds": ROUNDS,
                "processes_stopped": stopped,
                "note": scoring.get("note", ""),
            }
        )
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - a crash must still record a score
        write_report({"reward": 0.0, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})
        sys.exit(0)
