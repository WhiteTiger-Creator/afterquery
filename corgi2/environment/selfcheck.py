"""Local check: does the pipeline run, and how good are its predictions?

Scores against `data/dev.csv`, which was held out from training. Run it after any change
worth keeping.

One caveat that matters more here than it usually does. The development molecules have at
most one ring, like the training ones. The molecules this work is scored on all have two
or more. So this number is a floor on the error you should expect, not an estimate of it —
a change that helps here has probably helped, but the size of the help will shrink.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP = Path("/app")
SCORING = APP / "scoring.json"
DEV = APP / "data" / "dev.csv"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(DEV), help="csv with smiles and gap columns")
    args = ap.parse_args()

    source = Path(args.input)
    if not source.is_file():
        print(f"no such file: {source}", file=sys.stderr)
        return 2

    scoring = json.loads(SCORING.read_text())
    smiles: list[str] = []
    truth: list[float] = []
    with open(source, newline="") as fh:
        for row in csv.DictReader(fh):
            smiles.append(row["smiles"])
            truth.append(float(row["gap"]))

    work = Path(tempfile.mkdtemp(prefix="selfcheck-"))
    question = work / "molecules.csv"
    answer = work / "predictions.csv"
    with open(question, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["smiles"])
        for text in smiles:
            writer.writerow([text])

    started = time.time()
    proc = subprocess.run(
        ["/app/predict.sh", str(question), str(answer)], capture_output=True, text=True
    )
    elapsed = time.time() - started
    if proc.returncode != 0:
        print("predict.sh failed:", file=sys.stderr)
        print(proc.stdout + proc.stderr, file=sys.stderr)
        return 1

    predicted: list[float] = []
    problems = 0
    with open(answer, newline="") as fh:
        for index, row in enumerate(csv.DictReader(fh)):
            if index < len(smiles) and row.get("smiles") != smiles[index]:
                problems += 1
            try:
                value = float(row["gap"])
            except (TypeError, ValueError, KeyError):
                value = math.nan
            predicted.append(value)

    print(f"molecules      {len(smiles):,}")
    print(f"  predictions  {len(predicted):,}")
    if len(predicted) != len(smiles):
        print("  ROW COUNT MISMATCH — this scores zero")
        return 1
    if problems:
        print(f"  ORDER MISMATCH on {problems} rows — this scores zero")
        return 1
    if any(not math.isfinite(v) for v in predicted):
        print("  NON-FINITE VALUES — this scores zero")
        return 1

    mae = sum(abs(p - t) for p, t in zip(predicted, truth)) / len(truth)
    lo = scoring["baseline_mae"]
    hi = scoring["target_mae"]
    estimate = max(0.0, min(1.0, (lo - mae) / (lo - hi)))

    print(f"  predict      {elapsed:.1f}s")
    print()
    print(f"  dev MAE      {mae:.6f}")
    print(f"  baseline     {lo:.6f}      target {hi:.6f}")
    print(f"  estimate     {estimate:.3f}  (optimistic — see below)")
    print()
    print("  The graded molecules all have two or more rings; these have at most one.")
    print("  Expect the real error to be higher and the real gain to be smaller.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
