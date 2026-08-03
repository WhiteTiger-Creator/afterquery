"""The move model: features, scores, and exact integer frequencies.

A move is scored by summing learned weights indexed by a handful of features, and the
position's distribution is the softmax over the legal moves. Training minimises negative
log-likelihood, which is the same quantity the archive pays in bits, so the training loss
and the file size move together.

Two details matter for correctness rather than size:

* the encoder and decoder must derive byte-identical frequency tables, so the softmax is
  converted to integers by a fixed largest-remainder allocation, never by rounding each
  entry independently;
* weights are quantised once and stored quantised, so both directions score with exactly
  the same numbers.
"""

from __future__ import annotations

import numpy as np

# Feature blocks: (name, size). Indices are offset into one flat weight vector.
#
# The last three carry context the earlier ones cannot see. `recap_*` answer "does this
# move hit the square the opponent just moved to", which is most of what makes a capture
# predictable. `mat_piece_to` buckets the game by how much material is left rather than by
# how many moves have been played — the graded collection is dominated by faster time
# controls with longer games, so ply count means something different there than it does in
# the training corpus, while a count of pieces on the board does not.
BLOCKS = (
    ("piece_to", 16 * 64),
    ("from_to", 64 * 64),
    ("phase_piece_to", 6 * 16 * 64),
    ("piece_victim", 16 * 16),
    ("promo_piece", 4 * 16),
    ("phase_from", 6 * 64),
    ("recap_piece_victim", 2 * 16 * 16),
    ("recap_to", 2 * 64),
    ("mat_piece_to", 6 * 16 * 64),
)
SIZES = [size for _, size in BLOCKS]
OFFSETS = np.cumsum([0] + SIZES[:-1]).tolist()
TOTAL_WEIGHTS = int(sum(SIZES))

#: Denominator used for coded frequencies. Must stay below the coder's 2**16 ceiling and
#: comfortably above the largest legal move count so every move can hold at least one.
FREQ_TOTAL = 1 << 14

PROMO_CODE = {None: 0, 5: 1, 4: 2, 3: 3, 2: 0}  # queen, rook, bishop, knight->0


def phase_of(ply: int) -> int:
    return min(ply // 12, 5)


def material_phase(board) -> int:
    """Bucket the position by how much material is still on the board.

    Thirty-two pieces at the start down to a bare endgame. Unlike a ply counter this means
    the same thing regardless of how long the players took to get there.
    """
    remaining = bin(board.occupied).count("1")
    return min((32 - remaining) // 5, 5)


def feature_indices(piece, victim, frm, to, promo, phase, white, recap, mat):
    """Flat weight indices for one candidate move.

    Squares are mirrored for black so both colours share statistics; a knight developing
    to its third rank is the same event whichever side plays it.
    """
    if not white:
        frm ^= 56
        to ^= 56
    return (
        OFFSETS[0] + piece * 64 + to,
        OFFSETS[1] + frm * 64 + to,
        OFFSETS[2] + phase * (16 * 64) + piece * 64 + to,
        OFFSETS[3] + piece * 16 + victim,
        OFFSETS[4] + promo * 16 + piece,
        OFFSETS[5] + phase * 64 + frm,
        OFFSETS[6] + recap * (16 * 16) + piece * 16 + victim,
        OFFSETS[7] + recap * 64 + to,
        OFFSETS[8] + mat * (16 * 64) + piece * 64 + to,
    )


N_FEATURES = len(BLOCKS)


def board_features(board, moves, ply):
    """Feature indices for every legal move, as an (n, N_FEATURES) int array.

    The previous move is read from the board's own stack, so the encoder and decoder
    derive it identically — the decoder has pushed exactly the same moves by the time it
    reaches this position.
    """
    white = board.turn
    phase = phase_of(ply)
    mat = material_phase(board)
    prev_to = board.move_stack[-1].to_square if board.move_stack else -1

    rows = np.empty((len(moves), N_FEATURES), dtype=np.int32)
    for i, m in enumerate(moves):
        piece = board.piece_type_at(m.from_square) or 0
        victim = board.piece_type_at(m.to_square) or 0
        rows[i] = feature_indices(
            piece,
            victim,
            m.from_square,
            m.to_square,
            PROMO_CODE.get(m.promotion, 0),
            phase,
            white,
            1 if m.to_square == prev_to else 0,
            mat,
        )
    return rows


def scores_from(weights: np.ndarray, rows: np.ndarray) -> np.ndarray:
    return weights[rows].sum(axis=1)


def frequencies(scores: np.ndarray, total: int = FREQ_TOTAL) -> list[int]:
    """Turn scores into integer frequencies summing to exactly `total`.

    Every move gets at least 1 so nothing is unencodable, and the remainder is handed out
    by largest fractional part with ties broken by position. That makes the table a pure
    function of the scores — which is what lets the decoder rebuild it.
    """
    n = len(scores)
    if n == 1:
        return [total]
    if n >= total:
        raise ValueError(f"cannot allocate {total} over {n} symbols")

    shifted = scores - scores.max()
    exp = np.exp(shifted)
    probs = exp / exp.sum()

    spare = total - n
    exact = probs * spare
    base = np.floor(exact).astype(np.int64)
    leftover = spare - int(base.sum())
    if leftover:
        frac = exact - base
        # Descending fractional part; ties resolved by the earlier index.
        order = np.lexsort((np.arange(n), -frac))
        base[order[:leftover]] += 1
    return (base + 1).astype(np.int64).tolist()


def quantize_weights(weights: np.ndarray) -> tuple[np.ndarray, float]:
    """Quantise to int16 with a single shared scale."""
    peak = float(np.abs(weights).max())
    if peak == 0.0:
        return np.zeros(len(weights), dtype=np.int16), 1.0
    scale = peak / 32000.0
    q = np.clip(np.round(weights / scale), -32000, 32000).astype(np.int16)
    return q, scale


def dequantize_weights(q: np.ndarray, scale: float) -> np.ndarray:
    return q.astype(np.float64) * scale
