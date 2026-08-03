"""Command line entry point: ``python -m pgnpack compress|decompress``."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .codec import compress, decompress


def directory_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pgnpack")
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("compress", help="pack a PGN file into an archive directory")
    c.add_argument("input")
    c.add_argument("out_dir")

    d = sub.add_parser("decompress", help="rebuild a PGN file from an archive directory")
    d.add_argument("out_dir")
    d.add_argument("output")

    args = parser.parse_args(argv)

    started = time.time()
    if args.command == "compress":
        compress(args.input, args.out_dir)
        size = directory_size(Path(args.out_dir))
        original = Path(args.input).stat().st_size
        print(f"{original:,} -> {size:,} bytes  ({original / size:.2f}x)")
    else:
        decompress(args.out_dir, args.output)
        print(f"wrote {Path(args.output).stat().st_size:,} bytes")
    print(f"{time.time() - started:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
