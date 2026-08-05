"""Fit a model, save it, load it, predict with it.

Gradient boosting over the counts from `features`. Nothing here is tuned and nothing here
looks at molecular structure; it is a working end-to-end pipeline and a starting point,
not an attempt at a good answer.
"""

from __future__ import annotations

import csv
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from .features import featurise

MODEL_DIR = Path("/app/model")
MODEL_PATH = MODEL_DIR / "model.joblib"

TARGET = "gap"
SMILES_COLUMN = "smiles"


def read_table(path: str | Path, with_target: bool = True):
    """Read a csv of SMILES and, when present, their measured property."""
    smiles: list[str] = []
    values: list[float] = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        if SMILES_COLUMN not in (reader.fieldnames or []):
            raise ValueError(f"{path} has no '{SMILES_COLUMN}' column")
        for row in reader:
            smiles.append(row[SMILES_COLUMN])
            if with_target:
                values.append(float(row[TARGET]))
    return (smiles, np.array(values, dtype=np.float64)) if with_target else smiles


def train(train_csv: str | Path, out_path: str | Path = MODEL_PATH) -> Path:
    smiles, y = read_table(train_csv)
    features = featurise(smiles)
    model = HistGradientBoostingRegressor(
        max_iter=400,
        learning_rate=0.08,
        random_state=0,
    )
    model.fit(features, y)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, out_path)
    return out_path


def predict(input_csv: str | Path, output_csv: str | Path, model_path: str | Path = MODEL_PATH):
    """Write one prediction per input row, in the order they were given."""
    smiles = read_table(input_csv, with_target=False)
    model = joblib.load(model_path)
    values = model.predict(featurise(smiles))

    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["smiles", "gap"])
        for s, v in zip(smiles, values):
            writer.writerow([s, f"{float(v):.8f}"])
    return output_csv


def mean_absolute_error(predicted: np.ndarray, actual: np.ndarray) -> float:
    return float(np.abs(np.asarray(predicted) - np.asarray(actual)).mean())
