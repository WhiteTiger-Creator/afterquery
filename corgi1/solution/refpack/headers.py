"""Header modelling.

A general-purpose compressor sees the header block as interleaved records and has to
rediscover, over and over, that the third line of every game is a date. Splitting the
fields into columns and giving each one a transform suited to what it holds does much
better, and costs only the small tables needed to invert it.

Every transform here is exactly invertible, and every table it needs is written into the
stream, so the measured size is the whole cost.
"""

from __future__ import annotations

import lzma
import struct
from collections import Counter, defaultdict

SITE_PREFIX = "https://lichess.org/"
BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
B62_INDEX = {c: i for i, c in enumerate(BASE62)}


def _xz(data: bytes) -> bytes:
    return lzma.compress(data, preset=9 | lzma.PRESET_EXTREME)


def _unxz(data: bytes) -> bytes:
    return lzma.decompress(data)


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def _varints(nums) -> bytes:
    out = bytearray()
    for n in nums:
        out += _varint(n)
    return bytes(out)


def _read_varints(buf: bytes, count: int):
    out = []
    pos = 0
    for _ in range(count):
        shift = 0
        value = 0
        while True:
            b = buf[pos]
            pos += 1
            value |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
        out.append(value)
    return out


def _zig(n: int) -> int:
    return (n << 1) if n >= 0 else ((-n << 1) - 1)


def _unzig(n: int) -> int:
    return n >> 1 if n % 2 == 0 else -((n + 1) >> 1)


def _pack_sections(sections: list[bytes]) -> bytes:
    out = bytearray(struct.pack("<H", len(sections)))
    for blob in sections:
        out += struct.pack("<I", len(blob))
    for blob in sections:
        out += blob
    return bytes(out)


def _unpack_sections(buf: bytes) -> list[bytes]:
    (count,) = struct.unpack_from("<H", buf, 0)
    pos = 2
    lengths = []
    for _ in range(count):
        (n,) = struct.unpack_from("<I", buf, pos)
        pos += 4
        lengths.append(n)
    out = []
    for n in lengths:
        out.append(buf[pos : pos + n])
        pos += n
    return out


def _dict_encode(values: list[str]) -> tuple[bytes, bytes]:
    counts = Counter(values)
    vocab = [v for v, _ in counts.most_common()]
    index = {v: i for i, v in enumerate(vocab)}
    return (
        _xz("\n".join(vocab).encode("utf-8")),
        _xz(_varints(index[v] for v in values)),
    )


def _dict_decode(vocab_blob: bytes, index_blob: bytes, count: int) -> list[str]:
    vocab = _unxz(vocab_blob).decode("utf-8").split("\n") if vocab_blob else []
    idx = _read_varints(_unxz(index_blob), count)
    return [vocab[i] for i in idx]


def _site_encode(values: list[str]) -> bytes:
    ids = []
    for v in values:
        if not v.startswith(SITE_PREFIX):
            return b"\x00" + _xz("\n".join(values).encode("utf-8"))
        ids.append(v[len(SITE_PREFIX) :])
    if any(len(i) != 8 or any(c not in B62_INDEX for c in i) for i in ids):
        return b"\x00" + _xz("\n".join(values).encode("utf-8"))
    packed = bytearray()
    for i in ids:
        n = 0
        for c in i:
            n = n * 62 + B62_INDEX[c]
        packed += n.to_bytes(6, "big")
    return b"\x01" + bytes(packed)


def _site_decode(blob: bytes, count: int) -> list[str]:
    if blob[:1] == b"\x00":
        return _unxz(blob[1:]).decode("utf-8").split("\n")
    body = blob[1:]
    out = []
    for k in range(count):
        n = int.from_bytes(body[k * 6 : k * 6 + 6], "big")
        chars = []
        for _ in range(8):
            n, r = divmod(n, 62)
            chars.append(BASE62[r])
        out.append(SITE_PREFIX + "".join(reversed(chars)))
    return out


def _time_encode(values: list[str]) -> bytes:
    secs = []
    for v in values:
        try:
            h, m, s = (int(x) for x in v.split(":"))
        except ValueError:
            return b"\x00" + _xz("\n".join(values).encode("utf-8"))
        secs.append(h * 3600 + m * 60 + s)
    deltas = [secs[0]] + [secs[i] - secs[i - 1] for i in range(1, len(secs))]
    return b"\x01" + _xz(_varints(_zig(d) for d in deltas))


def _time_decode(blob: bytes, count: int) -> list[str]:
    if blob[:1] == b"\x00":
        return _unxz(blob[1:]).decode("utf-8").split("\n")
    deltas = [_unzig(v) for v in _read_varints(_unxz(blob[1:]), count)]
    out = []
    running = 0
    for i, d in enumerate(deltas):
        running = d if i == 0 else running + d
        h, rem = divmod(running, 3600)
        m, s = divmod(rem, 60)
        out.append(f"{h:02d}:{m:02d}:{s:02d}")
    return out


def _int_encode(values: list[str]) -> bytes:
    try:
        nums = [int(v) for v in values]
    except ValueError:
        return b"\x00" + _xz("\n".join(values).encode("utf-8"))
    # Keep the leading sign of values like "+5" / "-8" so the text round trips.
    signed = b"\x02" if any(v.startswith("+") for v in values) else b"\x01"
    return signed + _xz(_varints(_zig(n) for n in nums))


def _int_decode(blob: bytes, count: int) -> list[str]:
    tag = blob[:1]
    if tag == b"\x00":
        return _unxz(blob[1:]).decode("utf-8").split("\n")
    nums = [_unzig(v) for v in _read_varints(_unxz(blob[1:]), count)]
    if tag == b"\x02":
        return [f"+{n}" if n >= 0 else str(n) for n in nums]
    return [str(n) for n in nums]


def _opening_encode(eco: list[str], opening: list[str]) -> bytes:
    by_eco = defaultdict(Counter)
    for e, o in zip(eco, opening):
        by_eco[e][o] += 1
    modal = {e: c.most_common(1)[0][0] for e, c in by_eco.items()}
    keys = sorted(modal)
    table = _xz("\n".join(f"{k}\t{modal[k]}" for k in keys).encode("utf-8"))
    flags = bytearray()
    misses = []
    for e, o in zip(eco, opening):
        if modal.get(e) == o:
            flags.append(0)
        else:
            flags.append(1)
            misses.append(o)
    miss_vocab, miss_idx = _dict_encode(misses) if misses else (b"", b"")
    return _pack_sections([table, _xz(bytes(flags)), miss_vocab, miss_idx])


def _opening_decode(blob: bytes, eco: list[str], count: int) -> list[str]:
    table_blob, flag_blob, miss_vocab, miss_idx = _unpack_sections(blob)
    modal = {}
    text = _unxz(table_blob).decode("utf-8")
    if text:
        for line in text.split("\n"):
            k, _, v = line.partition("\t")
            modal[k] = v
    flags = _unxz(flag_blob)
    n_miss = sum(flags)
    misses = _dict_decode(miss_vocab, miss_idx, n_miss) if n_miss else []
    out = []
    cursor = 0
    for i in range(count):
        if flags[i]:
            out.append(misses[cursor])
            cursor += 1
        else:
            out.append(modal.get(eco[i], ""))
    return out


#: Fields handled by a dedicated transform. Everything else is dictionary coded.
SPECIAL = {"Site", "UTCTime", "WhiteElo", "BlackElo", "WhiteRatingDiff", "BlackRatingDiff"}


def encode(games: list[list[tuple[str, str]]]) -> bytes:
    """Encode per-game ordered header lists into one blob."""
    schemas = [tuple(k for k, _ in g) for g in games]
    schema_vocab = [s for s, _ in Counter(schemas).most_common()]
    schema_index = {s: i for i, s in enumerate(schema_vocab)}

    sections = [
        _xz("\n".join("\t".join(s) for s in schema_vocab).encode("utf-8")),
        _xz(_varints(schema_index[s] for s in schemas)),
    ]

    keys_in_order: list[str] = []
    columns: dict[str, list[str]] = defaultdict(list)
    for game in games:
        for key, value in game:
            if key not in columns:
                keys_in_order.append(key)
            columns[key].append(value)

    sections.append(_xz("\n".join(keys_in_order).encode("utf-8")))
    sections.append(_xz(_varints(len(columns[k]) for k in keys_in_order)))

    for key in keys_in_order:
        values = columns[key]
        if key == "Site":
            sections.append(_site_encode(values))
        elif key == "UTCTime":
            sections.append(_time_encode(values))
        elif key in ("WhiteElo", "BlackElo", "WhiteRatingDiff", "BlackRatingDiff"):
            sections.append(_int_encode(values))
        elif key == "Opening" and "ECO" in columns and len(columns["ECO"]) == len(values):
            sections.append(b"\xff" + _opening_encode(columns["ECO"], values))
        else:
            vocab, idx = _dict_encode(values)
            sections.append(b"\xfe" + _pack_sections([vocab, idx]))

    return _pack_sections(sections)


def decode(blob: bytes) -> list[list[tuple[str, str]]]:
    sections = _unpack_sections(blob)
    schema_text = _unxz(sections[0]).decode("utf-8")
    schema_vocab = [tuple(line.split("\t")) for line in schema_text.split("\n")]
    schema_ids = _read_varints(_unxz(sections[1]), 0) if False else None

    # Schema count is not known before decoding, so read greedily.
    raw = _unxz(sections[1])
    schema_ids = []
    pos = 0
    while pos < len(raw):
        shift = 0
        value = 0
        while True:
            b = raw[pos]
            pos += 1
            value |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
        schema_ids.append(value)
    schemas = [schema_vocab[i] for i in schema_ids]
    n_games = len(schemas)

    keys_in_order = _unxz(sections[2]).decode("utf-8").split("\n")
    counts = _read_varints(_unxz(sections[3]), len(keys_in_order))

    columns: dict[str, list[str]] = {}
    cursor = 4
    pending_opening = None
    for key, count in zip(keys_in_order, counts):
        blob_i = sections[cursor]
        cursor += 1
        if key == "Site":
            columns[key] = _site_decode(blob_i, count)
        elif key == "UTCTime":
            columns[key] = _time_decode(blob_i, count)
        elif key in ("WhiteElo", "BlackElo", "WhiteRatingDiff", "BlackRatingDiff"):
            columns[key] = _int_decode(blob_i, count)
        elif blob_i[:1] == b"\xff":
            pending_opening = (key, blob_i[1:], count)
            columns[key] = []
        else:
            vocab, idx = _unpack_sections(blob_i[1:])
            columns[key] = _dict_decode(vocab, idx, count)

    if pending_opening is not None:
        key, body, count = pending_opening
        columns[key] = _opening_decode(body, columns.get("ECO", []), count)

    cursors = {k: 0 for k in columns}
    games: list[list[tuple[str, str]]] = []
    for schema in schemas:
        game = []
        for key in schema:
            game.append((key, columns[key][cursors[key]]))
            cursors[key] += 1
        games.append(game)
    return games
