"""A small SMILES reader and fingerprint builder.

Enough of the grammar to cover neutral organic molecules of the kind this dataset holds:
atoms, bonds, branches, ring closures, aromatic lower-case atoms and bracketed atoms with
explicit hydrogen or charge. No stereochemistry — the property being predicted does not
depend on it here, and leaving it out keeps the parser small enough to trust.

The fingerprint is the usual circular-environment idea: hash each atom together with its
neighbourhood out to a small radius, and count how often each hash appears. Two molecules
that share substructures share bins, which is what lets a model trained on one part of
chemical space say something useful about another.
"""

from __future__ import annotations

import re
import zlib
from collections import defaultdict

import numpy as np

TOKEN = re.compile(
    r"""
    (?P<bracket>\[[^\]]+\])
  | (?P<organic>Br|Cl|[BCNOSPFIbcnosp])
  | (?P<bond>[=#\-:/\\])
  | (?P<branch_open>\()
  | (?P<branch_close>\))
  | (?P<ring>%\d{2}|\d)
    """,
    re.X,
)

BOND_ORDER = {"-": 1, "=": 2, "#": 3, ":": 4, "/": 1, "\\": 1}
AROMATIC = set("bcnosp")


class Mol:
    __slots__ = ("elements", "aromatic", "charges", "hydrogens", "bonds", "adj")

    def __init__(self) -> None:
        self.elements: list[str] = []
        self.aromatic: list[bool] = []
        self.charges: list[int] = []
        self.hydrogens: list[int] = []
        self.bonds: list[tuple[int, int, int]] = []
        self.adj: dict[int, list[tuple[int, int]]] = defaultdict(list)

    def add_atom(self, element: str, aromatic: bool, charge: int = 0, hydrogens: int = -1) -> int:
        self.elements.append(element)
        self.aromatic.append(aromatic)
        self.charges.append(charge)
        self.hydrogens.append(hydrogens)
        return len(self.elements) - 1

    def add_bond(self, a: int, b: int, order: int) -> None:
        self.bonds.append((a, b, order))
        self.adj[a].append((b, order))
        self.adj[b].append((a, order))

    def __len__(self) -> int:
        return len(self.elements)


def parse(smiles: str) -> Mol:
    """Read a SMILES string into a molecular graph."""
    mol = Mol()
    stack: list[int] = []
    previous: int | None = None
    pending_bond: int | None = None
    ring_open: dict[str, tuple[int, int | None]] = {}

    for match in TOKEN.finditer(smiles):
        kind = match.lastgroup
        text = match.group()

        if kind == "branch_open":
            stack.append(previous)
            continue
        if kind == "branch_close":
            previous = stack.pop()
            continue
        if kind == "bond":
            pending_bond = BOND_ORDER.get(text, 1)
            continue
        if kind == "ring":
            key = text.lstrip("%")
            if key in ring_open:
                partner, order = ring_open.pop(key)
                mol.add_bond(previous, partner, order or pending_bond or 1)
            else:
                ring_open[key] = (previous, pending_bond)
            pending_bond = None
            continue

        if kind == "bracket":
            body = text[1:-1]
            element = re.match(r"[A-Za-z][a-z]?", body.lstrip("0123456789"))
            symbol = element.group() if element else "C"
            hydro = re.search(r"H(\d*)", body)
            n_h = int(hydro.group(1) or 1) if hydro else 0
            charge = 0
            for sign, digits in re.findall(r"([+-])(\d*)", body):
                charge += (1 if sign == "+" else -1) * int(digits or 1)
            index = mol.add_atom(symbol.upper(), symbol[0] in AROMATIC, charge, n_h)
        else:
            index = mol.add_atom(text.upper(), text[0] in AROMATIC, 0, -1)

        if previous is not None:
            mol.add_bond(previous, index, pending_bond or (4 if mol.aromatic[index] and mol.aromatic[previous] else 1))
        pending_bond = None
        previous = index

    return mol


def ring_sizes(mol: Mol) -> list[int]:
    """Smallest cycle through each bond that closes a ring, found by breadth-first search."""
    sizes = []
    for a, b, _ in mol.bonds:
        # Remove this bond and look for the shortest remaining path between its ends.
        seen = {a: 0}
        queue = [a]
        while queue:
            node = queue.pop(0)
            for nxt, _order in mol.adj[node]:
                if node == a and nxt == b:
                    continue
                if nxt == b and node == a:
                    continue
                if nxt not in seen:
                    seen[nxt] = seen[node] + 1
                    queue.append(nxt)
            if b in seen:
                break
        if b in seen:
            sizes.append(seen[b] + 1)
    return sizes


def _stable_hash(value) -> int:
    """A hash that does not change between processes.

    Python salts str hashing per interpreter, so the builtin would put the same
    substructure in different bins during training and prediction. Everything downstream
    of this depends on the two agreeing exactly.
    """
    return zlib.crc32(repr(value).encode("utf-8")) & 0xFFFFFFFF


def fingerprint(mol: Mol, bits: int = 2048, radius: int = 2) -> np.ndarray:
    """Counts of hashed circular atom environments."""
    out = np.zeros(bits, dtype=np.float32)
    labels = [
        _stable_hash((mol.elements[i], mol.aromatic[i], mol.charges[i], len(mol.adj[i])))
        for i in range(len(mol))
    ]
    for _ in range(radius + 1):
        for label in labels:
            out[label % bits] += 1.0
        labels = [
            _stable_hash((labels[i], tuple(sorted((labels[j], o) for j, o in mol.adj[i]))))
            for i in range(len(mol))
        ]
    return out


def descriptors(mol: Mol) -> list[float]:
    """Global quantities a fingerprint does not capture well."""
    n = len(mol)
    if n == 0:
        return [0.0] * 20
    counts = defaultdict(int)
    for e in mol.elements:
        counts[e] += 1
    orders = defaultdict(int)
    for _a, _b, o in mol.bonds:
        orders[o] += 1
    degrees = [len(mol.adj[i]) for i in range(n)]
    sizes = ring_sizes(mol)
    aromatic_atoms = sum(mol.aromatic)
    return [
        n,
        len(mol.bonds),
        counts["C"], counts["N"], counts["O"], counts["F"],
        orders[1], orders[2], orders[3], orders[4],
        aromatic_atoms,
        aromatic_atoms / n,
        sum(degrees) / n,
        max(degrees),
        degrees.count(1), degrees.count(2), degrees.count(3), degrees.count(4),
        len(mol.bonds) - n + 1,             # cycles by Euler's formula
        float(np.mean(sizes)) if sizes else 0.0,
    ]
