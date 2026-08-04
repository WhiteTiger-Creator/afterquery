"""Score a submission.

The measurement is deliberately blunt. Pack the graded archive, throw the original away,
unpack it, and require the result to match byte for byte. Then add up everything the
submission needed in order to have done that, and turn the total into a score against two
fixed reference points.

Correctness is a gate, not a component: a rebuild that differs anywhere scores zero no
matter how small the archive was. There is no way for a crash, a timeout, or a missing
file to produce anything but zero.

The interesting problem is that packing and unpacking run in the same container, so the
cheapest possible "compressor" is one that writes the original somewhere and reads it back
later. Guarding a fixed list of directories does not close that — there is always another
writable path, and naming subtrees to skip is worse still, since a name like /dev looks
inert while containing /dev/shm, which is a tmpfs that will hold gigabytes quite happily.

So the rule here is stated over behaviour rather than location, and the exclusions are
derived from the live mount table rather than written down: every filesystem is walked
unless its type cannot store a regular file at all. The entire filesystem is snapshotted
before packing, and anything created or altered while packing, outside the archive
directory itself, is both charged to the footprint and deleted before the rebuild runs. Stashing the corpus therefore costs exactly as much as putting it in the
archive would have, and it is gone by the time the rebuild could read it. Processes started
during packing are killed for the same reason: a daemon holding the plaintext in memory is
just a stash with extra steps.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
APP = Path("/app")

GRADED_PGN = DATA / "graded.pgn"
MANIFEST = DATA / "manifest.json"
SCORING = DATA / "scoring.json"

REPORT_DIR = Path(os.environ.get("REWARD_DIR", "/logs/verifier"))

COMPRESS_TIMEOUT = int(os.environ.get("COMPRESS_TIMEOUT", "2400"))
DECOMPRESS_TIMEOUT = int(os.environ.get("DECOMPRESS_TIMEOUT", "2400"))

#: Subtrees of /app whose contents are derived rather than authored. They are exempt from
#: the manifest comparison, but NOT from the filesystem diff below — otherwise they would
#: be the one place under /app where bytes could be parked for free.
DERIVED_SUBDIRS = ("__pycache__", ".timer", ".git")

#: Files the platform's timer daemon owns and rewrites continuously. They are tiny, fixed
#: in name, and not under the submission's control, so churn in them is ignored rather than
#: charged — anything else appearing in .timer is treated like any other stash.
TIMER_FILES = frozenset(
    {
        "timer.pid",
        "start_epoch",
        "budget_secs",
        "remaining_secs",
        "elapsed_secs",
        "alert_30min",
        "alert_10min",
        "alert_5min",
    }
)

#: Filesystem types that cannot hold an ordinary file a submission could park bytes in.
#: Anything not on this list is walked, whatever it is mounted as — the exclusions are
#: derived from the live mount table rather than from a list of paths, because a path list
#: is only ever as good as the author's imagination. /dev is a case in point: most of it is
#: device nodes, but /dev/shm is a perfectly ordinary tmpfs that will happily hold
#: gigabytes, so excluding the subtree by name would leave a hole.
INERT_FSTYPES = frozenset(
    {
        "autofs",
        "binfmt_misc",
        "bpf",
        "cgroup",
        "cgroup2",
        "configfs",
        "debugfs",
        "devpts",
        "fusectl",
        "mqueue",
        "nsfs",
        "proc",
        "pstore",
        "rpc_pipefs",
        "securityfs",
        "selinuxfs",
        "sysfs",
        "tracefs",
    }
)


def inert_mountpoints() -> tuple[str, ...]:
    """Mount points whose filesystem cannot store a regular file.

    Read from /proc/mounts so that a filesystem nobody anticipated is scanned by default
    rather than skipped by default. /proc and /sys are added unconditionally: if the mount
    table cannot be read at all, those two still must not be walked.
    """
    skip = {"/proc", "/sys"}
    try:
        for line in Path("/proc/mounts").read_text().splitlines():
            fields = line.split()
            if len(fields) >= 3 and fields[2] in INERT_FSTYPES:
                skip.add(fields[1])
    except OSError:
        pass
    return tuple(sorted(skip))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def unshipped_bytes(manifest: dict) -> tuple[int, list[dict]]:
    """Bytes under /app that are new or altered relative to the shipped manifest.

    Without this, the cheapest way to shrink an archive is to move the model into a source
    file and pretend it was always there.
    """
    total = 0
    details: list[dict] = []
    for path in sorted(APP.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            rel = path.relative_to(APP).as_posix()
        except ValueError:  # pragma: no cover - defensive
            continue
        if any(part in DERIVED_SUBDIRS for part in rel.split("/")):
            continue
        entry = manifest.get(rel)
        size = path.stat().st_size
        if entry is None:
            total += size
            details.append({"path": rel, "bytes": size, "why": "added"})
        elif entry["sha256"] != sha256_file(path):
            total += size
            details.append({"path": rel, "bytes": size, "why": "modified"})
    return total, details


# --------------------------------------------------------------------------- filesystem

def _excluded(path: str, extra: tuple[str, ...]) -> bool:
    for root in extra:
        if path == root or path.startswith(root + "/"):
            return True
    return False


def snapshot_tree(extra_excludes: tuple[str, ...]) -> dict[str, tuple[int, int]]:
    """Record (size, ctime) for every regular file on the filesystem.

    `st_ctime_ns` moves whenever an inode is written and cannot be set backwards by
    `utime`, so a submission cannot hide a modification by restoring timestamps.
    """
    snap: dict[str, tuple[int, int]] = {}
    stack = ["/"]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    path = entry.path
                    if _excluded(path, extra_excludes):
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


def _chargeable(path: str) -> bool:
    """Whether a changed path counts as a stash.

    Files under /app are already priced by the manifest, except inside the derived
    subtrees — those are exempt from the manifest and so must be priced here instead. The
    timer daemon's own files are the single exception, because the platform rewrites them
    on its own schedule and their churn has nothing to do with the submission.
    """
    if path.startswith("/app/"):
        rel = path[len("/app/") :]
        parts = rel.split("/")
        if not any(part in DERIVED_SUBDIRS for part in parts):
            return False  # priced by the manifest
        if ".timer" in parts and parts[-1] in TIMER_FILES:
            return False
    return True


def diff_and_scrub(
    before: dict[str, tuple[int, int]], extra_excludes: tuple[str, ...]
) -> tuple[int, list[dict]]:
    """Charge and remove everything written outside the archive while packing."""
    after = snapshot_tree(extra_excludes)
    total = 0
    details: list[dict] = []

    for path, meta in sorted(after.items()):
        if before.get(path) == meta:
            continue
        if not _chargeable(path):
            continue
        size = meta[0]
        total += size
        details.append(
            {
                "path": path,
                "bytes": size,
                "why": "created" if path not in before else "modified",
            }
        )
        try:
            os.unlink(path)
        except OSError:
            pass

    return total, details


# ----------------------------------------------------------------------------- processes

def snapshot_pids() -> set[int]:
    return {int(p.name) for p in Path("/proc").iterdir() if p.name.isdigit()}


def _ancestry(pid: int) -> list[int]:
    chain = []
    for _ in range(64):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except OSError:
            break
        try:
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
        except (IndexError, ValueError):
            break
        chain.append(ppid)
        if ppid <= 1:
            break
        pid = ppid
    return chain


def kill_new_processes(before: set[int]) -> list[int]:
    """Stop anything the packing step left running.

    A process started while packing could be holding the corpus in memory and handing it
    back during the rebuild. The verifier's own ancestry is left alone.
    """
    me = os.getpid()
    protected = {me, 1} | set(_ancestry(me))
    killed = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in before or pid in protected:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append(pid)
        except OSError:
            pass
    return killed


# -------------------------------------------------------------------------------- report

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


def run(cmd: list[str], timeout: int) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except OSError as exc:
        return False, f"could not run {cmd[0]}: {exc}"
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr)[-2000:]
        return False, f"exit {proc.returncode}: {tail}"
    return True, ""


def main() -> int:
    for required in (GRADED_PGN, MANIFEST, SCORING):
        if not required.is_file():
            return fail(f"verifier data missing: {required.name}")

    scoring = json.loads(SCORING.read_text())
    manifest = json.loads(MANIFEST.read_text())
    baseline_ratio = float(scoring["baseline_ratio"])
    target_ratio = float(scoring["target_ratio"])

    compress_sh = APP / "compress.sh"
    decompress_sh = APP / "decompress.sh"
    for script in (compress_sh, decompress_sh):
        if not script.is_file():
            return fail(f"{script} is missing")
        if not os.access(script, os.X_OK):
            return fail(f"{script} is not executable")

    work = Path(tempfile.mkdtemp(prefix="grade-", dir="/tmp"))
    source = work / "input.pgn"
    archive = work / "archive"
    rebuilt = work / "rebuilt.pgn"

    # Everything is walked except filesystems that cannot hold a regular file, plus the
    # verifier's own data and working area. The archive lives inside the working area and
    # is exempt because producing it is the whole point.
    inert = inert_mountpoints()
    excludes = inert + (str(HERE), str(REPORT_DIR), str(work))

    try:
        pids_before = snapshot_pids()
        tree_before = snapshot_tree(excludes)

        shutil.copyfile(GRADED_PGN, source)
        original_bytes = source.stat().st_size
        original_digest = sha256_file(GRADED_PGN)

        started = time.time()
        ok, why = run([str(compress_sh), str(source), str(archive)], COMPRESS_TIMEOUT)
        pack_secs = time.time() - started
        if not ok:
            return fail(f"compress.sh failed — {why}")
        if not archive.is_dir():
            return fail("compress.sh did not create the archive directory")

        archive_bytes = directory_size(archive)

        # The rebuild must come from the archive alone: not from the file we just packed,
        # not from anything parked elsewhere on disk, and not from a process still holding
        # it in memory.
        source.unlink()
        killed = kill_new_processes(pids_before)
        stashed_bytes, stashed_detail = diff_and_scrub(tree_before, excludes)

        # Anything left loose in the working directory is a stash too, but the archive and
        # the file we are about to write are not.
        for stray in work.iterdir():
            if stray in (archive, rebuilt):
                continue
            size = directory_size(stray) if stray.is_dir() else stray.stat().st_size
            stashed_bytes += size
            stashed_detail.append({"path": str(stray), "bytes": size, "why": "created"})
            if stray.is_dir():
                shutil.rmtree(stray, ignore_errors=True)
            else:
                stray.unlink(missing_ok=True)

        started = time.time()
        ok, why = run([str(decompress_sh), str(archive), str(rebuilt)], DECOMPRESS_TIMEOUT)
        unpack_secs = time.time() - started
        if not ok:
            return fail(f"decompress.sh failed — {why}", stashed_bytes=stashed_bytes)
        if not rebuilt.is_file():
            return fail("decompress.sh did not produce an output file")

        if sha256_file(rebuilt) != original_digest:
            return fail(
                "rebuilt archive does not match the original",
                rebuilt_bytes=rebuilt.stat().st_size,
                original_bytes=original_bytes,
            )

        unshipped, unshipped_detail = unshipped_bytes(manifest)
        footprint = archive_bytes + unshipped + stashed_bytes
        if footprint <= 0:
            return fail("footprint measured as zero")

        ratio = original_bytes / footprint
        span = target_ratio - baseline_ratio
        raw = (ratio - baseline_ratio) / span if span > 0 else 0.0
        reward = max(0.0, min(1.0, raw))

        write_report(
            {
                "reward": round(reward, 6),
                "status": "scored",
                "original_bytes": original_bytes,
                "archive_bytes": archive_bytes,
                "unshipped_bytes": unshipped,
                "stashed_bytes": stashed_bytes,
                "footprint_bytes": footprint,
                "ratio": round(ratio, 6),
                "baseline_ratio": baseline_ratio,
                "target_ratio": target_ratio,
                "unclipped": round(raw, 6),
                "compress_seconds": round(pack_secs, 1),
                "decompress_seconds": round(unpack_secs, 1),
                "unshipped_detail": unshipped_detail[:50],
                "stashed_detail": stashed_detail[:50],
                "processes_killed": len(killed),
                "excluded_mounts": list(inert),
            }
        )
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
