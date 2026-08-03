"""pgnpack — a lossless archive format for chess game collections."""

from __future__ import annotations

from .codec import ARCHIVE_NAME, compress, decompress

__all__ = ["ARCHIVE_NAME", "compress", "decompress"]
