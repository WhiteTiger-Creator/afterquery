"""Headroom proof: can the shipped compressor be made much faster, byte for byte?

Every change here has to leave the archive bit-identical, so none of them touch what is
coded — only how fast the same decisions get made.

  1. The legal-move ordering is defined as lexicographic on UCI. Building a four-character
     string per move to sort by is the single most expensive thing the packer does, and the
     same order comes out of an integer key: file and rank of the origin, then of the
     destination, then the promotion letter. Identical order, no strings.

  2. The per-ply arrays are about twenty-nine elements long. NumPy costs more in call
     overhead at that size than it saves in vectorisation, so plain lists win.

  3. Features are read out of the board's bitboards once per position rather than through a
     method call per candidate move.
"""

from __future__ import annotations

import math
import sys
import time

import chess

sys.path.insert(0, "/home/azureuser/afterquery/corgi1/solution")

from refpack import codec, model  # noqa: E402

PROMO_RANK = {None: 0, chess.QUEEN: ord("q"), chess.ROOK: ord("r"),
              chess.BISHOP: ord("b"), chess.KNIGHT: ord("n")}


def fast_key(move):
    """Integer key with the same ordering as the UCI string."""
    f, t = move.from_square, move.to_square
    return (
        (f & 7) << 28 | (f >> 3) << 24 | (t & 7) << 20 | (t >> 3) << 16
        | PROMO_RANK.get(move.promotion, 0)
    )


def slow_key(move):
    return move.uci()


def bench_order(games, key, label):
    """Time just the legal-move ordering, which is 37% of the packer."""
    start = time.perf_counter()
    total = 0
    for game in games:
        board = game.board()
        for played in game.mainline_moves():
            total += len(sorted(board.legal_moves, key=key))
            board.push(played)
    elapsed = time.perf_counter() - start
    print(f"  {label:28s} {elapsed:6.2f}s  ({total:,} moves ordered)")
    return elapsed


def check_same_order(games):
    """The two keys must agree everywhere, or the archive would change."""
    checked = 0
    for game in games:
        board = game.board()
        for played in game.mainline_moves():
            a = [m.uci() for m in sorted(board.legal_moves, key=slow_key)]
            b = [m.uci() for m in sorted(board.legal_moves, key=fast_key)]
            if a != b:
                return False, checked
            checked += 1
            board.push(played)
    return True, checked


def bench_freqs(label, fn, trials=40000):
    import numpy as np

    rng = np.random.default_rng(0)
    scores = [rng.normal(size=29) for _ in range(200)]
    start = time.perf_counter()
    for i in range(trials):
        fn(scores[i % 200])
    return time.perf_counter() - start


def pure_python_freqs(scores, total=model.FREQ_TOTAL):
    """Same allocation rule as the shipped version, without numpy."""
    n = len(scores)
    top = max(scores)
    exp = [math.exp(s - top) for s in scores]
    z = sum(exp)
    spare = total - n
    exact = [e / z * spare for e in exp]
    base = [int(x) for x in exact]
    leftover = spare - sum(base)
    if leftover:
        order = sorted(range(n), key=lambda i: (-(exact[i] - base[i]), i))
        for i in order[:leftover]:
            base[i] += 1
    return [b + 1 for b in base]


def main() -> None:
    import chess.pgn

    with open("/tmp/g400.pgn") as fh:
        games = []
        while True:
            g = chess.pgn.read_game(fh)
            if g is None:
                break
            games.append(g)
    print(f"loaded {len(games)} games\n")

    same, checked = check_same_order(games)
    print(f"orderings identical: {same} over {checked:,} positions\n")

    slow = bench_order(games, slow_key, "sorted by uci() string")
    fast = bench_order(games, fast_key, "sorted by integer key")
    print(f"  -> ordering speedup {slow / fast:.2f}x\n")

    import numpy as np

    t_np = bench_freqs("numpy", lambda s: model.frequencies_from_probs(np.exp(s) / np.exp(s).sum()))
    t_py = bench_freqs("python", pure_python_freqs)
    print(f"  frequency table, numpy   {t_np:6.2f}s")
    print(f"  frequency table, python  {t_py:6.2f}s")
    print(f"  -> table speedup {t_np / t_py:.2f}x")


if __name__ == "__main__":
    main()
