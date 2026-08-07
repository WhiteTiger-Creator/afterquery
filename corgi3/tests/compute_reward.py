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

import hashlib
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
SOLVE_TIMEOUT = int(os.environ.get("SOLVE_TIMEOUT", "9000"))
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


#: Filesystem types that cannot hold an ordinary file. Everything else is walked, whatever
#: it is mounted as — the exclusions come from the live mount table rather than from a list
#: of paths, because a path list is only ever as good as the author's imagination. /dev is
#: the case in point: mostly device nodes, but /dev/shm is a tmpfs that holds gigabytes.
INERT_FSTYPES = frozenset({
    "autofs", "binfmt_misc", "bpf", "cgroup", "cgroup2", "configfs", "debugfs", "devpts",
    "fusectl", "mqueue", "nsfs", "proc", "pstore", "rpc_pipefs", "securityfs", "selinuxfs",
    "sysfs", "tracefs",
})


def inert_mountpoints() -> tuple:
    skip = {"/proc", "/sys"}
    try:
        for line in Path("/proc/mounts").read_text().splitlines():
            fields = line.split()
            if len(fields) >= 3 and fields[2] in INERT_FSTYPES:
                skip.add(fields[1])
    except OSError:
        pass
    return tuple(sorted(skip))


def snapshot(root: Path) -> set:
    return {p for p in root.rglob("*") if p.is_file()}


def snapshot_tree(excludes: tuple) -> dict:
    """(size, ctime) for every regular file anywhere the submission could write.

    A cache does not have to live under /app. It can go in /tmp, /dev/shm, /var, or
    anywhere else in a container that lives for the whole grading run, so the sweep covers
    all of it. `st_ctime_ns` moves on any write and cannot be set backwards by `utime`.
    """
    snap = {}
    stack = ["/"]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    path = entry.path
                    if any(path == x or path.startswith(x + "/") for x in excludes):
                        continue
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(path)
                        elif entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            snap[path] = (st.st_size, st.st_ctime_ns)
                    except OSError:
                        continue
        except OSError:
            continue
    return snap


def scrub_tree(before: dict, excludes: tuple) -> int:
    """Delete everything written anywhere since the snapshot."""
    removed = 0
    for path, meta in sorted(snapshot_tree(excludes).items()):
        if before.get(path) == meta:
            continue
        try:
            os.unlink(path)
            removed += 1
        except OSError:
            pass
    return removed


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


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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

    # The network is the input to both sides of the comparison, and it lives where the
    # submission can write. A substituted graph could cripple the interpreted reference
    # while leaving a compiled candidate untouched, inflating the ratio without any of the
    # work the task is about. So: check it against the hash recorded when the task was
    # built, then take a copy out of reach and run everything from that instead. The check
    # catches substitution, the copy closes the gap between checking and using.
    expected = scoring.get("network_sha256")
    if expected:
        actual = sha256_file(GRAPH)
        if actual != expected:
            return fail(
                "the road network under /app/data has been altered",
                expected_sha256=expected,
                found_sha256=actual,
            )
    graph = work / "road.gr.gz"
    shutil.copy2(GRAPH, graph)

    try:
        # ---------------------------------------------------------- preparation
        pids_before = live_pids()
        prepare_sh = APP / "prepare.sh"
        prepare_seconds = 0.0
        if prepare_sh.is_file() and os.access(prepare_sh, os.X_OK):
            proc, why, prepare_seconds = run(
                [prepare_sh, graph], PREPARE_TIMEOUT, cwd="/app", env=env
            )
            if proc is None:
                return fail(f"prepare.sh failed — {why}")

        # Preparation has to leave its results on disk. Anything it left *running* is
        # stopped here, before a single measurement is taken: a process that survives into
        # the timed rounds can memoise the answers it sees on the first one and hand them
        # back free on the next two, which measures caching rather than speed.
        stopped = kill_new(pids_before)

        excludes = inert_mountpoints() + (str(HERE), str(REPORT_DIR), str(work))
        before_rounds = snapshot_tree(excludes)
        pids_after_prepare = live_pids()
        scrubbed = 0

        # ---------------------------------------------------------- timed rounds
        base_times: list[float] = []
        cand_times: list[float] = []
        reference: list[str] | None = None

        for round_index in range(ROUNDS):
            base_out = work / f"base_{round_index}.txt"
            proc, why, seconds = run(
                [sys.executable, "-m", "router", graph, QUERIES, base_out],
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
                [solve_sh, graph, QUERIES, cand_out], SOLVE_TIMEOUT, cwd="/app", env=env
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

            scrubbed += scrub_tree(before_rounds, excludes)
            stopped += kill_new(pids_after_prepare)

        base = statistics.median(base_times)
        cand = statistics.median(cand_times)
        if cand <= 0:
            return fail("measured time was zero, which cannot be right")

        # Parity with the shipped implementation scores 1.0; every further factor of
        # speed adds half a point. Correctness has already been established above, and
        # without it nothing here is reached.
        ratio = base / cand
        reward = 0.5 + 0.5 * ratio

        write_report(
            {
                "reward": round(reward, 6),
                "status": "scored",
                "correct": True,
                "ratio": round(ratio, 4),

                "baseline_seconds": [round(x, 3) for x in base_times],
                "candidate_seconds": [round(x, 3) for x in cand_times],
                "baseline_median": round(base, 3),
                "candidate_median": round(cand, 3),
                "prepare_seconds": round(prepare_seconds, 1),
                "queries": n_queries,
                "rounds": ROUNDS,
                "processes_stopped": stopped,
                "files_scrubbed": scrubbed,
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
