"""The baseline archive format.

The idea is the only one that matters at this level: a chess move does not need to be
spelled out, because both sides of the channel can generate the list of legal moves in
the current position. All that has to be transmitted is *which* of them was played. With
about 29 legal moves in a typical position that costs a shade under five bits, against
roughly seven bytes for the text of the move.

Everything else here is deliberately plain. The headers are handed to a general-purpose
compressor as one blob; move selection is coded as if every legal move were equally
likely. Both are obvious places to do better.

Format of `archive.bin`:

    magic "PGNP", u8 version
    u32 game_count
    u32 header_len,  bzip2(header blob)
    u32 plies_len,   bzip2(varint ply counts)
    u32 moves_len,   range-coded move indices

The header blob is one record per game: ``key \x01 value \x02`` repeated, then \x03.
"""

from __future__ import annotations

import bz2
import io
import struct
from pathlib import Path

import chess
import chess.pgn

from .rangecoder import RangeDecoder, RangeEncoder, decode_uniform, encode_uniform

MAGIC = b"PGNP"
VERSION = 1
ARCHIVE_NAME = "archive.bin"

FIELD_SEP = b"\x01"
RECORD_SEP = b"\x02"
GAME_SEP = b"\x03"


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


def legal_moves(board: chess.Board) -> list[chess.Move]:
    """The legal moves in a fixed order both sides agree on.

    Sorting by UCI is arbitrary but stable, which is all that is required: the encoder
    and decoder only need to produce the same list from the same position.
    """
    return sorted(board.legal_moves, key=lambda m: m.uci())


def canonical_text(game: chess.pgn.Game) -> str:
    """Render a game in the archive's canonical form."""
    exporter = chess.pgn.StringExporter(
        headers=True, variations=False, comments=False, columns=80
    )
    return game.accept(exporter) + "\n\n"


def read_games(text: str):
    stream = io.StringIO(text)
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            return
        yield game


def compress(input_path: str | Path, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    text = Path(input_path).read_text(encoding="utf-8")

    header_blob = bytearray()
    ply_counts = bytearray()
    enc = RangeEncoder()
    games = 0

    for game in read_games(text):
        for key, value in game.headers.items():
            header_blob += key.encode("utf-8") + FIELD_SEP
            header_blob += value.encode("utf-8") + RECORD_SEP
        header_blob += GAME_SEP

        board = game.board()
        plies = 0
        for played in game.mainline_moves():
            moves = legal_moves(board)
            encode_uniform(enc, moves.index(played), len(moves))
            board.push(played)
            plies += 1
        ply_counts += _varint(plies)
        games += 1

    headers_c = bz2.compress(bytes(header_blob), 9)
    plies_c = bz2.compress(bytes(ply_counts), 9)
    moves_c = enc.finish()

    archive = out_dir / ARCHIVE_NAME
    with open(archive, "wb") as fh:
        fh.write(MAGIC)
        fh.write(struct.pack("<BI", VERSION, games))
        fh.write(struct.pack("<I", len(headers_c)))
        fh.write(headers_c)
        fh.write(struct.pack("<I", len(plies_c)))
        fh.write(plies_c)
        fh.write(struct.pack("<I", len(moves_c)))
        fh.write(moves_c)
    return archive


def decompress(out_dir: str | Path, output_path: str | Path) -> Path:
    out_dir = Path(out_dir)
    blob = (out_dir / ARCHIVE_NAME).read_bytes()
    if blob[:4] != MAGIC:
        raise ValueError("not a pgnpack archive")
    version, games = struct.unpack_from("<BI", blob, 4)
    if version != VERSION:
        raise ValueError(f"unsupported archive version {version}")
    pos = 9

    (n,) = struct.unpack_from("<I", blob, pos)
    pos += 4
    header_blob = bz2.decompress(blob[pos : pos + n])
    pos += n

    (n,) = struct.unpack_from("<I", blob, pos)
    pos += 4
    ply_blob = bz2.decompress(blob[pos : pos + n])
    pos += n

    (n,) = struct.unpack_from("<I", blob, pos)
    pos += 4
    dec = RangeDecoder(blob[pos : pos + n])

    records = header_blob.split(GAME_SEP)[:games]
    out = io.StringIO()
    cursor = 0
    for index in range(games):
        plies, cursor = _read_varint(ply_blob, cursor)

        game = chess.pgn.Game()
        for key in list(game.headers.keys()):
            del game.headers[key]
        for field in records[index].split(RECORD_SEP):
            if not field:
                continue
            key, value = field.split(FIELD_SEP, 1)
            game.headers[key.decode("utf-8")] = value.decode("utf-8")

        board = game.board()
        node = game
        for _ in range(plies):
            moves = legal_moves(board)
            move = moves[decode_uniform(dec, len(moves))]
            node = node.add_variation(move)
            board.push(move)

        out.write(canonical_text(game))

    output_path = Path(output_path)
    output_path.write_text(out.getvalue(), encoding="utf-8", newline="")
    return output_path
