"""refpack — the reference archive format."""

from __future__ import annotations

from .codec import ARCHIVE_NAME, compress, decompress

__all__ = ["ARCHIVE_NAME", "compress", "decompress"]
