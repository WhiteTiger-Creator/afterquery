"""The reference answer.

Two changes to the shipped pipeline, and the second one matters more than it looks.

First, the molecule is actually read. SMILES is parsed into a graph and turned into counts
of hashed circular atom environments — which substructures are present, not which
characters are. Symbol counts cannot distinguish two molecules with the same formula and
different connectivity; the property being predicted very much can.

Second, the prediction is a blend of gradient boosting and ridge regression. Boosting is
the better model on molecules resembling the training set and the worse one off it: trees
cannot extrapolate past the leaves they were fit on, and every graded molecule has more
rings than anything in training. A modest weight on the linear part degrades more
gracefully. The blend is worth about three percent relative, which is not nothing when the
whole gap between careless and careful is fifteen.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

from .smiles import descriptors, fingerprint, parse

MODEL_DIR = Path("/app/model")
BUNDLE = MODEL_DIR / "reference.joblib"

BITS = 2048
RADIUS = 2
BLEND = 0.2  # weight on the linear component

TARGET = "gap"
SMILES_COLUMN = "smiles"


def read_table(path, with_target: bool = True):
    smiles: list[str] = []
    values: list[float] = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            smiles.append(row[SMILES_COLUMN])
            if with_target:
                values.append(float(row[TARGET]))
    return (smiles, np.array(values, dtype=np.float64)) if with_target else smiles


def featurise(smiles_list) -> np.ndarray:
    rows = []
    for text in smiles_list:
        mol = parse(text)
        if len(mol) == 0:
            rows.append(np.zeros(BITS + 20, dtype=np.float32))
            continue
        rows.append(
            np.concatenate(
                [
                    fingerprint(mol, bits=BITS, radius=RADIUS),
                    np.array(descriptors(mol), dtype=np.float32),
                ]
            )
        )
    return np.vstack(rows)


def train(train_csv, out_path=BUNDLE) -> Path:
    smiles, y = read_table(train_csv)
    features = featurise(smiles)

    booster = HistGradientBoostingRegressor(
        max_iter=600,
        learning_rate=0.06,
        max_leaf_nodes=63,
        random_state=0,
    ).fit(features, y)
    linear = Ridge(alpha=5.0).fit(features, y)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"booster": booster, "linear": linear, "blend": BLEND, "bits": BITS, "radius": RADIUS},
        out_path,
        compress=3,
    )
    return out_path


def predict(input_csv, output_csv, model_path=BUNDLE) -> Path:
    smiles = read_table(input_csv, with_target=False)
    bundle = joblib.load(model_path)
    features = featurise(smiles)
    blended = (1.0 - bundle["blend"]) * bundle["booster"].predict(features) + bundle[
        "blend"
    ] * bundle["linear"].predict(features)

    output_csv = Path(output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["smiles", "gap"])
        for text, value in zip(smiles, blended):
            writer.writerow([text, f"{float(value):.8f}"])
    return output_csv
