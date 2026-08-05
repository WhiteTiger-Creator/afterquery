"""The reference archive format.

Same skeleton as the shipped baseline, with the one substitution that matters: instead of
treating every legal move as equally likely, each move's probability comes from the
trained model, and the range coder is driven with those frequencies. Headers are still
handed to a general-purpose compressor here; the header model lives in `headers.py` and is
layered on top.

The decoder rebuilds the identical frequency table for every ply because it reaches the
same position, generates the same legal move list in the same order, and scores it with
the same quantised weights.
"""

from __future__ import annotations

import bz2
import io
import struct
from pathlib import Path

import chess
import chess.pgn
import numpy as np

from . import headers as headers_mod
from .model import (
    BOOK_MAX_PLY,
    FREQ_TOTAL,
    blend_book,
    board_features,
    dequantize_weights,
    frequencies_from_probs,
    probabilities,
)
from .rangecoder import RangeDecoder, RangeEncoder


class Book:
    """What has been played from each position so far in this archive.

    Keyed on the position itself rather than on the moves that reached it, so transpositions
    share evidence. Only the opening is remembered: past forty plies almost every position
    is unique, and storing them costs memory for nothing.
    """

    __slots__ = ("_counts",)

    def __init__(self) -> None:
        self._counts: dict[tuple, np.ndarray] = {}

    def lookup(self, board, ply: int):
        if ply >= BOOK_MAX_PLY:
            return None
        return self._counts.get(board._transposition_key())

    def record(self, board, ply: int, index: int, n_moves: int) -> None:
        if ply >= BOOK_MAX_PLY:
            return
        key = board._transposition_key()
        counts = self._counts.get(key)
        if counts is None:
            counts = self._counts[key] = np.zeros(n_moves, dtype=np.float64)
        counts[index] += 1.0

MAGIC = b"RPK1"
VERSION = 1
ARCHIVE_NAME = "archive.bin"

FIELD_SEP = b"\x01"
RECORD_SEP = b"\x02"
GAME_SEP = b"\x03"


def legal_moves(board: chess.Board) -> list[chess.Move]:
    """Legal moves in a fixed order both sides agree on."""
    return sorted(board.legal_moves, key=lambda m: m.uci())


def canonical_text(game: chess.pgn.Game) -> str:
    exporter = chess.pgn.StringExporter(
        headers=True, variations=False, comments=False, columns=80
    )
    return game.accept(exporter) + "\n\n"


def load_weights(path: str | Path) -> np.ndarray:
    """Read quantised weights, transparently handling the xz-compressed form.

    The compressed form is what ships: int16 weights compress to about a third of their
    raw size, and every byte of the model counts toward the archive's total.
    """
    path = Path(path)
    if path.suffix == ".xz":
        import lzma

        with lzma.open(path, "rb") as fh:
            scale = float(np.load(fh)[0])
            q = np.load(fh)
    else:
        with open(path, "rb") as fh:
            scale = float(np.load(fh)[0])
            q = np.load(fh)
    return dequantize_weights(q, scale)


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    shift = 0
    value = 0
    while True:
        b = buf[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, pos
        shift += 7


def _cumulative(freqs: list[int], index: int) -> int:
    return sum(freqs[:index])


def compress(input_path, out_dir, weights_path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    weights = load_weights(weights_path)
    text = Path(input_path).read_text(encoding="utf-8")

    header_games: list[list[tuple[str, str]]] = []
    ply_counts = bytearray()
    enc = RangeEncoder()
    book = Book()
    games = 0

    stream = io.StringIO(text)
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        header_games.append(list(game.headers.items()))

        board = game.board()
        plies = 0
        for played in game.mainline_moves():
            moves = legal_moves(board)
            index = moves.index(played)
            if len(moves) == 1:
                board.push(played)
                plies += 1
                continue
            rows = board_features(board, moves, plies)
            probs = probabilities(weights[rows].sum(axis=1))
            probs = blend_book(probs, book.lookup(board, plies))
            freqs = frequencies_from_probs(probs)
            enc.encode(_cumulative(freqs, index), freqs[index], FREQ_TOTAL)
            book.record(board, plies, index, len(moves))
            board.push(played)
            plies += 1
        ply_counts += _varint(plies)
        games += 1

    headers_c = headers_mod.encode(header_games)
    plies_c = bz2.compress(bytes(ply_counts), 9)
    moves_c = enc.finish()

    archive = out_dir / ARCHIVE_NAME
    with open(archive, "wb") as fh:
        fh.write(MAGIC)
        fh.write(struct.pack("<BI", VERSION, games))
        for chunk in (headers_c, plies_c, moves_c):
            fh.write(struct.pack("<I", len(chunk)))
            fh.write(chunk)
    return archive


def decompress(out_dir, output_path, weights_path) -> Path:
    out_dir = Path(out_dir)
    weights = load_weights(weights_path)
    blob = (out_dir / ARCHIVE_NAME).read_bytes()
    if blob[:4] != MAGIC:
        raise ValueError("not a refpack archive")
    version, games = struct.unpack_from("<BI", blob, 4)
    if version != VERSION:
        raise ValueError(f"unsupported archive version {version}")
    pos = 9

    chunks = []
    for _ in range(3):
        (n,) = struct.unpack_from("<I", blob, pos)
        pos += 4
        chunks.append(blob[pos : pos + n])
        pos += n
    header_games = headers_mod.decode(chunks[0])
    ply_blob = bz2.decompress(chunks[1])
    dec = RangeDecoder(chunks[2])

    book = Book()
    out = io.StringIO()
    cursor = 0
    for gi in range(games):
        plies, cursor = _read_varint(ply_blob, cursor)

        game = chess.pgn.Game()
        for key in list(game.headers.keys()):
            del game.headers[key]
        for key, value in header_games[gi]:
            game.headers[key] = value

        board = game.board()
        node = game
        for ply in range(plies):
            moves = legal_moves(board)
            if len(moves) == 1:
                move = moves[0]
            else:
                rows = board_features(board, moves, ply)
                probs = probabilities(weights[rows].sum(axis=1))
                probs = blend_book(probs, book.lookup(board, ply))
                freqs = frequencies_from_probs(probs)
                target = dec.get_freq(FREQ_TOTAL)
                running = 0
                index = 0
                for i, f in enumerate(freqs):
                    if running + f > target:
                        index = i
                        break
                    running += f
                dec.decode(running, freqs[index])
                book.record(board, ply, index, len(moves))
                move = moves[index]
            node = node.add_variation(move)
            board.push(move)

        out.write(canonical_text(game))

    output_path = Path(output_path)
    output_path.write_text(out.getvalue(), encoding="utf-8", newline="")
    return output_path
