"""Locations for data bundled with the backend executable."""

from __future__ import annotations

import sys
from pathlib import Path


def bundled_root() -> Path:
    """Return the repository root in development or PyInstaller's data root."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[3]


def bundled_path(*parts: str) -> Path:
    return bundled_root().joinpath(*parts)


def source_path(*parts: str) -> Path:
    """Return a source-tree asset in development or a bundled asset at runtime."""
    if getattr(sys, "_MEIPASS", None):
        return bundled_path(*parts)
    return bundled_root().joinpath("src", *parts)
