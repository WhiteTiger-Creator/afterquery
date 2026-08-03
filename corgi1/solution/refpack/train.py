"""Fit the move model on a PGN corpus.

One pass extracts features for every legal move in every position; then plain SGD on the
conditional log-likelihood. The loss printed each epoch is bits per move, which is
directly the quantity the archive pays, so it can be read as a size forecast.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

import chess
import chess.pgn
import numpy as np

from .codec import legal_moves
from .model import TOTAL_WEIGHTS, board_features, quantize_weights


def extract(pgn_path: str, max_games: int):
    rows = []
    starts = []
    lengths = []
    chosen = []
    cursor = 0
    games = 0
    started = time.time()

    with open(pgn_path, encoding="utf-8") as fh:
        while games < max_games:
            game = chess.pgn.read_game(fh)
            if game is None:
                break
            board = game.board()
            ply = 0
            for played in game.mainline_moves():
                moves = legal_moves(board)
                if not moves:
                    break
                rows.append(board_features(board, moves, ply))
                starts.append(cursor)
                lengths.append(len(moves))
                chosen.append(cursor + moves.index(played))
                cursor += len(moves)
                board.push(played)
                ply += 1
            games += 1
            if games % 2000 == 0:
                print(
                    f"  extracted {games} games  {games / (time.time() - started):.0f}/s",
                    flush=True,
                )

    return (
        np.concatenate(rows).astype(np.int32),
        np.array(starts, dtype=np.int64),
        np.array(lengths, dtype=np.int32),
        np.array(chosen, dtype=np.int64),
        games,
    )


def segment_softmax(scores, starts, lengths):
    seg = np.repeat(np.arange(len(starts)), lengths)
    peak = np.maximum.reduceat(scores, starts)
    exp = np.exp(scores - peak[seg])
    denom = np.add.reduceat(exp, starts)
    return exp / denom[seg], seg


def train(rows, starts, lengths, chosen, epochs, lr, l2, batch, seed):
    rng = np.random.default_rng(seed)
    w = np.zeros(TOTAL_WEIGHTS, dtype=np.float64)
    n_pos = len(starts)

    for epoch in range(epochs):
        started = time.time()
        order = rng.permutation(n_pos)
        for chunk in range(0, n_pos, batch):
            sel = order[chunk : chunk + batch]
            s, ln = starts[sel], lengths[sel]
            idx = np.concatenate([np.arange(a, a + b) for a, b in zip(s, ln)])
            local_starts = np.cumsum(np.concatenate([[0], ln[:-1]]))
            local_chosen = local_starts + (chosen[sel] - s)

            block = rows[idx]
            scores = w[block].sum(axis=1)
            probs, _ = segment_softmax(scores, local_starts, ln)

            grad_rows = probs.copy()
            grad_rows[local_chosen] -= 1.0
            grad = np.zeros_like(w)
            for c in range(block.shape[1]):
                np.add.at(grad, block[:, c], grad_rows)
            grad /= len(sel)
            w -= lr * (grad + l2 * w)

        scores = w[rows].sum(axis=1)
        probs, _ = segment_softmax(scores, starts, lengths)
        bits = float(-np.log2(probs[chosen]).mean())
        floor = float(np.log2(lengths.astype(np.float64)).mean())
        print(
            f"  epoch {epoch + 1}/{epochs}  {bits:.4f} bits/move"
            f"  (floor {floor:.4f}, {100 * (1 - bits / floor):+.1f}%)"
            f"  {time.time() - started:.0f}s",
            flush=True,
        )
    return w


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="refpack.train")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--games", type=int, default=12000)
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--lr", type=float, default=0.8)
    ap.add_argument("--l2", type=float, default=1e-6)
    ap.add_argument("--batch", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument(
        "--eval-corpus",
        default="",
        help="optional second collection to report bits/move on after training",
    )
    ap.add_argument("--eval-games", type=int, default=3000)
    args = ap.parse_args(argv)

    print(f"extracting from {args.corpus} ...", flush=True)
    rows, starts, lengths, chosen, games = extract(args.corpus, args.games)
    print(
        f"{games} games  {len(starts):,} positions  {len(rows):,} candidates",
        flush=True,
    )

    w = train(
        rows, starts, lengths, chosen,
        args.epochs, args.lr, args.l2, args.batch, args.seed,
    )

    if args.eval_corpus:
        print(f"evaluating on {args.eval_corpus} ...", flush=True)
        e_rows, e_starts, e_lengths, e_chosen, e_games = extract(
            args.eval_corpus, args.eval_games
        )
        scores = w[e_rows].sum(axis=1)
        probs, _ = segment_softmax(scores, e_starts, e_lengths)
        bits = float(-np.log2(probs[e_chosen]).mean())
        floor = float(np.log2(e_lengths.astype(np.float64)).mean())
        print(
            f"  {e_games} games  {len(e_starts):,} positions\n"
            f"  floor {floor:.4f}  model {bits:.4f} bits/move  ({100 * (1 - bits / floor):+.1f}%)",
            flush=True,
        )

    q, scale = quantize_weights(w)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        np.save(fh, np.array([scale], dtype=np.float64))
        np.save(fh, q)
    print(f"weights -> {out} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
