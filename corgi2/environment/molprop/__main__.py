"""Command line: ``python -m molprop train|predict``."""

from __future__ import annotations

import argparse
import sys
import time

from .model import MODEL_PATH, predict, train


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="molprop")
    sub = parser.add_subparsers(dest="command", required=True)

    t = sub.add_parser("train", help="fit a model and save it")
    t.add_argument("--data", default="/app/data/train.csv")
    t.add_argument("--out", default=str(MODEL_PATH))

    p = sub.add_parser("predict", help="predict for a csv of SMILES")
    p.add_argument("input")
    p.add_argument("output")
    p.add_argument("--model", default=str(MODEL_PATH))

    args = parser.parse_args(argv)
    started = time.time()
    if args.command == "train":
        path = train(args.data, args.out)
        print(f"model -> {path} ({path.stat().st_size:,} bytes)")
    else:
        out = predict(args.input, args.output, args.model)
        print(f"predictions -> {out}")
    print(f"{time.time() - started:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
