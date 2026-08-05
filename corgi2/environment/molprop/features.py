"""Turning a SMILES string into numbers.

What is here is the crude version: count the characters. It knows how many carbons and
nitrogens a molecule has, roughly how many rings, how many double bonds. It does not know
what is bonded to what, which is most of what determines the property being predicted.

That is the obvious place to do better, and doing better means actually reading the
structure rather than counting symbols.
"""

from __future__ import annotations

import re

import numpy as np

HEAVY = re.compile(r"Cl|Br|[BCNOFIPS]")
DIGIT = re.compile(r"\d")

#: Names line up with the columns produced by `featurise`, for anything that wants to
#: inspect what the model is looking at.
COLUMNS = (
    "heavy_atoms",
    "length",
    "carbon",
    "nitrogen",
    "oxygen",
    "fluorine",
    "aromatic_c",
    "aromatic_n",
    "aromatic_o",
    "double_bonds",
    "triple_bonds",
    "branches",
    "ring_closures",
    "ring_digit_1",
    "ring_digit_2",
    "ring_digit_3",
    "bracket_atoms",
)


def featurise_one(smiles: str) -> list[float]:
    """Seventeen counts describing one molecule."""
    return [
        len(HEAVY.findall(smiles)),
        len(smiles),
        smiles.count("C"),
        smiles.count("N"),
        smiles.count("O"),
        smiles.count("F"),
        smiles.count("c"),
        smiles.count("n"),
        smiles.count("o"),
        smiles.count("="),
        smiles.count("#"),
        smiles.count("("),
        len(DIGIT.findall(smiles)) // 2,
        smiles.count("1"),
        smiles.count("2"),
        smiles.count("3"),
        smiles.count("["),
    ]


def featurise(smiles_list) -> np.ndarray:
    """Feature matrix for a sequence of SMILES strings."""
    return np.array([featurise_one(s) for s in smiles_list], dtype=np.float32)
