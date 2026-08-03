"""Score a submission.

The measurement is deliberately blunt. Pack the graded archive, throw the original away,
unpack it, and require the result to match byte for byte. Then add up everything the
submission needs in order to have done that — the archive directory plus anything left
under /app that was not shipped — and turn that total into a score against two fixed
reference points.

Correctness is a gate, not a component: a rebuild that differs anywhere scores zero no
matter how small the archive was. There is no way for a crash, a timeout, or a missing
file to produce anything but zero.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
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

#: Directories under /app whose contents are derived rather than authored. Everything
#: else that differs from the manifest counts against the submission.
IGNORED_PREFIXES = ("__pycache__", ".timer", ".git")


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
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(APP).as_posix()
        except ValueError:  # pragma: no cover - defensive
            continue
        if any(part in IGNORED_PREFIXES for part in rel.split("/")):
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


#: Places a submission could stash data between packing and unpacking. Both halves run in
#: the same container, so without clearing these the corpus could simply be left in /tmp
#: during compression and read back during the rebuild, costing nothing.
SCRATCH_DIRS = ("/tmp", "/var/tmp", "/dev/shm", "/root", "/home", "/opt", "/srv")


def snapshot_scratch() -> dict[str, set[str]]:
    snap: dict[str, set[str]] = {}
    for d in SCRATCH_DIRS:
        p = Path(d)
        if p.is_dir():
            try:
                snap[d] = set(os.listdir(d))
            except OSError:
                snap[d] = set()
    return snap


def scrub_scratch(snap: dict[str, set[str]], keep: Path) -> list[str]:
    """Remove anything created outside /app and the archive since the snapshot."""
    removed = []
    for d, before in snap.items():
        try:
            current = set(os.listdir(d))
        except OSError:
            continue
        for name in current - before:
            target = Path(d) / name
            if target == keep or keep.is_relative_to(target):
                continue
            try:
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink(missing_ok=True)
                removed.append(str(target))
            except OSError:
                pass
    return removed


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

    try:
        scratch_before = snapshot_scratch()
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

        # The rebuild must come from the archive, not from the file we just packed, and
        # not from anything left lying around during packing.
        source.unlink()
        scrubbed = scrub_scratch(scratch_before, work)

        started = time.time()
        ok, why = run([str(decompress_sh), str(archive), str(rebuilt)], DECOMPRESS_TIMEOUT)
        unpack_secs = time.time() - started
        if not ok:
            return fail(f"decompress.sh failed — {why}")
        if not rebuilt.is_file():
            return fail("decompress.sh did not produce an output file")

        if sha256_file(rebuilt) != original_digest:
            return fail(
                "rebuilt archive does not match the original",
                rebuilt_bytes=rebuilt.stat().st_size,
                original_bytes=original_bytes,
            )

        archive_bytes = directory_size(archive)
        extra_bytes, extra_detail = unshipped_bytes(manifest)
        footprint = archive_bytes + extra_bytes
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
                "unshipped_bytes": extra_bytes,
                "footprint_bytes": footprint,
                "ratio": round(ratio, 6),
                "baseline_ratio": baseline_ratio,
                "target_ratio": target_ratio,
                "unclipped": round(raw, 6),
                "compress_seconds": round(pack_secs, 1),
                "decompress_seconds": round(unpack_secs, 1),
                "unshipped_detail": extra_detail[:50],
                "scrubbed_paths": len(scrubbed),
            }
        )
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
