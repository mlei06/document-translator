"""Shared repository helper."""

from typing import Any

from sqlalchemy import CursorResult

__all__ = ["rowcount"]


def rowcount(result: Any) -> int:
    """Rows an UPDATE or DELETE changed."""
    return int(result.rowcount) if isinstance(result, CursorResult) else 0
