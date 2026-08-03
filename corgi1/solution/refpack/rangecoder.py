"""A carryless range coder.

Byte-oriented rather than bit-oriented: this runs in Python and the inner loop is the
whole cost. Frequencies are integers and the total must stay below 2**16.

The encoder and decoder must be driven with identical frequency tables in identical
order. That is the entire contract, and it is what makes the round trip exact.
"""

from __future__ import annotations

TOP = 1 << 24
BOT = 1 << 16
MASK = 0xFFFFFFFF


class RangeEncoder:
    __slots__ = ("low", "rng", "out")

    def __init__(self) -> None:
        self.low = 0
        self.rng = MASK
        self.out = bytearray()

    def encode(self, cum_freq: int, freq: int, tot_freq: int) -> None:
        if freq <= 0 or cum_freq + freq > tot_freq or tot_freq > BOT:
            raise ValueError(f"bad interval cum={cum_freq} freq={freq} tot={tot_freq}")
        self.rng //= tot_freq
        self.low = (self.low + cum_freq * self.rng) & MASK
        self.rng = (self.rng * freq) & MASK
        while True:
            if (self.low ^ (self.low + self.rng)) < TOP:
                pass
            elif self.rng < BOT:
                self.rng = (-self.low) & (BOT - 1)
            else:
                break
            self.out.append((self.low >> 24) & 0xFF)
            self.low = (self.low << 8) & MASK
            self.rng = (self.rng << 8) & MASK

    def finish(self) -> bytes:
        for _ in range(4):
            self.out.append((self.low >> 24) & 0xFF)
            self.low = (self.low << 8) & MASK
        return bytes(self.out)


class RangeDecoder:
    __slots__ = ("low", "rng", "code", "buf", "pos")

    def __init__(self, data: bytes) -> None:
        self.low = 0
        self.rng = MASK
        self.buf = data
        self.pos = 0
        self.code = 0
        for _ in range(4):
            self.code = ((self.code << 8) | self._byte()) & MASK

    def _byte(self) -> int:
        if self.pos < len(self.buf):
            b = self.buf[self.pos]
            self.pos += 1
            return b
        self.pos += 1
        return 0

    def get_freq(self, tot_freq: int) -> int:
        if tot_freq > BOT:
            raise ValueError("total frequency too large")
        self.rng //= tot_freq
        value = ((self.code - self.low) & MASK) // self.rng
        return tot_freq - 1 if value >= tot_freq else value

    def decode(self, cum_freq: int, freq: int) -> None:
        self.low = (self.low + cum_freq * self.rng) & MASK
        self.rng = (self.rng * freq) & MASK
        while True:
            if (self.low ^ (self.low + self.rng)) < TOP:
                pass
            elif self.rng < BOT:
                self.rng = (-self.low) & (BOT - 1)
            else:
                break
            self.code = ((self.code << 8) | self._byte()) & MASK
            self.low = (self.low << 8) & MASK
            self.rng = (self.rng << 8) & MASK


def encode_uniform(enc: RangeEncoder, index: int, count: int) -> None:
    """Spend exactly log2(count) bits selecting one of `count` equally likely symbols."""
    enc.encode(index, 1, count)


def decode_uniform(dec: RangeDecoder, count: int) -> int:
    index = dec.get_freq(count)
    dec.decode(index, 1)
    return index
