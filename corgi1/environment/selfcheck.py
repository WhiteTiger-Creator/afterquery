"""Local check: does the archive round trip, how big is it, and roughly what does it score?

Run this often. It exercises exactly what the score cares about — an exact rebuild and a
total footprint — on a local holdout, so a change that helps here is very likely to help
on the graded archive too.

The footprint counts two things: everything written into the archive directory, and any
file under /app that differs from the shipped manifest. Moving bytes out of the archive
and into a source file therefore buys nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP = Path("/app")
MANIFEST = APP / "manifest.json"
SCORING = APP / "scoring.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def directory_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def added_bytes(manifest: dict) -> tuple[int, list[str]]:
    """Bytes under /app that are new or changed relative to the shipped manifest."""
    total = 0
    changed: list[str] = []
    ignored = ("__pycache__", ".timer", ".git")
    for path in sorted(APP.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(APP).as_posix()
        if any(part in ignored for part in rel.split("/")):
            continue
        if rel == "manifest.json":
            # The shipped manifest cannot list its own hash; the scored copy does.
            continue
        entry = manifest.get(rel)
        if entry is None or entry["sha256"] != sha256(path):
            size = path.stat().st_size
            total += size
            changed.append(f"{rel} ({size:,} bytes)")
    return total, changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--input",
        default=str(APP / "corpus" / "holdout.pgn"),
        help="PGN file to test against (default: the local holdout)",
    )
    ap.add_argument("--keep", action="store_true", help="leave the work directory in place")
    args = ap.parse_args()

    source = Path(args.input)
    if not source.is_file():
        print(f"no such file: {source}", file=sys.stderr)
        return 2

    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.is_file() else {}
    scoring = json.loads(SCORING.read_text())

    work = Path(tempfile.mkdtemp(prefix="selfcheck-"))
    archive = work / "archive"
    rebuilt = work / "rebuilt.pgn"
    try:
        original = source.stat().st_size

        started = time.time()
        proc = subprocess.run(
            ["/app/compress.sh", str(source), str(archive)],
            capture_output=True,
            text=True,
        )
        pack_secs = time.time() - started
        if proc.returncode != 0:
            print("compress.sh failed:", file=sys.stderr)
            print(proc.stdout + proc.stderr, file=sys.stderr)
            return 1

        started = time.time()
        proc = subprocess.run(
            ["/app/decompress.sh", str(archive), str(rebuilt)],
            capture_output=True,
            text=True,
        )
        unpack_secs = time.time() - started
        if proc.returncode != 0:
            print("decompress.sh failed:", file=sys.stderr)
            print(proc.stdout + proc.stderr, file=sys.stderr)
            return 1

        exact = source.read_bytes() == rebuilt.read_bytes()
        archive_bytes = directory_size(archive)
        extra_bytes, changed = added_bytes(manifest)
        footprint = archive_bytes + extra_bytes

        print(f"input           {source}")
        print(f"  original      {original:,} bytes")
        print(f"  archive       {archive_bytes:,} bytes")
        if extra_bytes:
            print(f"  added to /app {extra_bytes:,} bytes")
            for line in changed[:10]:
                print(f"      {line}")
        print(f"  footprint     {footprint:,} bytes")
        print(f"  round trip    {'EXACT' if exact else 'MISMATCH — scores zero'}")
        print(f"  pack {pack_secs:.1f}s   unpack {unpack_secs:.1f}s")

        if not exact:
            return 1

        ratio = original / footprint
        lo = scoring["baseline_ratio"]
        hi = scoring["target_ratio"]
        estimate = max(0.0, min(1.0, (ratio - lo) / (hi - lo)))
        print()
        print(f"  ratio         {ratio:.4f}x")
        print(f"  baseline      {lo:.4f}x      target {hi:.4f}x")
        print(f"  estimate      {estimate:.3f}")
        print()
        if original < 1_000_000:
            print("  NOTE: this input is small. Anything with a fixed cost — a model, a")
            print("  dictionary, a table — is amortised over far fewer games here than on")
            print("  the graded collection, so the ratio understates what the same code")
            print("  achieves there. Use the full holdout before believing a number.")
            print()
        print("  The graded archive is a different collection of games, so treat this as a")
        print("  direction, not a promise. Improvements that only fit this file will not")
        print("  survive there.")
        return 0
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
