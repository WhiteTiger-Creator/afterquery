"""Package a task directory into a submission zip.

Lives outside /tmp so it survives session cleanup. Skips build noise and local harness
output, checks the required files are present, and prints what went in.
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "/home/azureuser/afterquery/corgi3")
OUT = ROOT.with_suffix(".zip")

SKIP_PARTS = {"__pycache__", ".git", ".pytest_cache", "jobs", ".venv", "build", "model"}
SKIP_SUFFIX = (".pyc", ".pyo", ".swp", ".so", ".o", ".c")
REQUIRED = [
    "task.toml",
    "instruction.md",
    "environment/Dockerfile",
    "environment/timer.sh",
    "tests/test.sh",
    "tests/compute_reward.py",
    "solution/solve.sh",
]


def main() -> int:
    missing = [r for r in REQUIRED if not (ROOT / r).is_file()]
    if missing:
        print(f"MISSING REQUIRED FILES: {missing}", file=sys.stderr)
        return 1

    files = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(part in SKIP_PARTS for part in rel.split("/")):
            continue
        if rel.endswith(SKIP_SUFFIX):
            continue
        files.append((path, rel))

    if OUT.exists():
        OUT.unlink()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path, rel in files:
            zf.write(path, rel)

    raw = sum(p.stat().st_size for p, _ in files)
    size = OUT.stat().st_size
    cap = 250 * 1024 * 1024
    print(f"{len(files)} files, {raw:,} bytes raw -> {OUT} ({size:,} bytes)")
    print(f"  {'OK' if size < cap else 'TOO LARGE'} against the 250 MB cap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
