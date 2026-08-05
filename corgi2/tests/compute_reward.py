"""Score a submission.

Hand the molecules over without their measured values, ask for a prediction for each one,
and see how close the answers are. The score is how far the mean absolute error has moved
from what the shipped pipeline achieves toward what a careful one does.

The measured values never leave this directory. The file handed to predict.sh carries only
structures, so there is nothing to read back and no way to score well except by predicting
well. Everything else is a gate: a missing row, a reordered row, a value that is not a
finite number, a crash, or a run over time all score zero.
"""

from __future__ import annotations

import csv
import json
import math
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

GRADED = DATA / "graded.csv"
SCORING = DATA / "scoring.json"

REPORT_DIR = Path(os.environ.get("REWARD_DIR", "/logs/verifier"))
PREDICT_TIMEOUT = int(os.environ.get("PREDICT_TIMEOUT", "3600"))

SMILES_COLUMN = "smiles"
TARGET_COLUMN = "gap"


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


def workspace_holds_answers(pairs: list[str], sample: int = 60, threshold: int = 5) -> str | None:
    """Look for the measured values themselves sitting somewhere under /app.

    A submission has no legitimate reason to hold `smiles,gap` pairs for molecules it was
    never given. Finding several of them in one file means the answers were obtained rather
    than predicted, whatever route they came by.
    """
    wanted = pairs[:sample]
    for path in APP.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            if path.stat().st_size > 512 * 1024 * 1024:
                continue
            blob = path.read_bytes()
        except OSError:
            continue
        hits = sum(1 for text in wanted if text.encode() in blob)
        if hits >= threshold:
            return f"{path.relative_to(APP).as_posix()} ({hits} of {len(wanted)} sampled values)"
    return None


def main() -> int:
    for required in (GRADED, SCORING):
        if not required.is_file():
            return fail(f"verifier data missing: {required.name}")

    scoring = json.loads(SCORING.read_text())
    baseline_mae = float(scoring["baseline_mae"])
    target_mae = float(scoring["target_mae"])

    predict_sh = APP / "predict.sh"
    if not predict_sh.is_file():
        return fail("/app/predict.sh is missing")
    if not os.access(predict_sh, os.X_OK):
        return fail("/app/predict.sh is not executable")

    smiles: list[str] = []
    truth: list[float] = []
    with open(GRADED, newline="") as fh:
        for row in csv.DictReader(fh):
            smiles.append(row[SMILES_COLUMN])
            truth.append(float(row[TARGET_COLUMN]))

    # Deterministic stride through the collection, so the sample does not depend on a seed.
    step = max(1, len(smiles) // 60)
    fingerprints = [f"{smiles[i]},{truth[i]}" for i in range(0, len(smiles), step)][:60]
    found = workspace_holds_answers(fingerprints)
    if found is not None:
        return fail(f"measured values for the graded molecules were found in {found}")

    work = Path(tempfile.mkdtemp(prefix="grade-", dir="/tmp"))
    question = work / "molecules.csv"
    answer = work / "predictions.csv"
    try:
        # Structures only. The measured values stay in this directory.
        with open(question, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow([SMILES_COLUMN])
            for text in smiles:
                writer.writerow([text])

        started = time.time()
        try:
            proc = subprocess.run(
                [str(predict_sh), str(question), str(answer)],
                capture_output=True,
                text=True,
                timeout=PREDICT_TIMEOUT,
                cwd="/app",
            )
        except subprocess.TimeoutExpired:
            return fail(f"predict.sh exceeded {PREDICT_TIMEOUT}s")
        except OSError as exc:
            return fail(f"predict.sh could not be run: {exc}")
        elapsed = time.time() - started

        if proc.returncode != 0:
            tail = (proc.stdout + proc.stderr)[-2000:]
            return fail(f"predict.sh exited {proc.returncode}: {tail}")
        if not answer.is_file():
            return fail("predict.sh produced no output file")

        predicted: list[float] = []
        with open(answer, newline="") as fh:
            reader = csv.DictReader(fh)
            fields = reader.fieldnames or []
            if SMILES_COLUMN not in fields or TARGET_COLUMN not in fields:
                return fail(f"predictions need '{SMILES_COLUMN}' and '{TARGET_COLUMN}' columns")
            for index, row in enumerate(reader):
                if index >= len(smiles):
                    return fail("predictions file has more rows than molecules")
                if row[SMILES_COLUMN] != smiles[index]:
                    return fail(
                        "predictions are not in the order the molecules were given",
                        first_mismatch_row=index + 1,
                    )
                try:
                    value = float(row[TARGET_COLUMN])
                except (TypeError, ValueError):
                    return fail(f"row {index + 1} has a value that is not a number")
                if not math.isfinite(value):
                    return fail(f"row {index + 1} is not a finite number")
                predicted.append(value)

        if len(predicted) != len(smiles):
            return fail(
                "one prediction per molecule is required",
                expected=len(smiles),
                received=len(predicted),
            )

        total = sum(abs(p - t) for p, t in zip(predicted, truth))
        mae = total / len(truth)

        span = baseline_mae - target_mae
        raw = (baseline_mae - mae) / span if span > 0 else 0.0
        reward = max(0.0, min(1.0, raw))

        write_report(
            {
                "reward": round(reward, 6),
                "status": "scored",
                "mae": round(mae, 8),
                "baseline_mae": baseline_mae,
                "target_mae": target_mae,
                "unclipped": round(raw, 6),
                "molecules": len(truth),
                "predict_seconds": round(elapsed, 1),
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
