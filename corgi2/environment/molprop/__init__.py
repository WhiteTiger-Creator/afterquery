"""molprop — predict a molecular property from structure."""

from __future__ import annotations

from .model import mean_absolute_error, predict, train

__all__ = ["mean_absolute_error", "predict", "train"]
