"""Run lifecycle disposition used by optimizer checkpoint finalization and IO."""
from __future__ import annotations

from enum import Enum


class RunDisposition(str, Enum):
    """Explicit execution lifecycle state used by checkpoint finalization."""

    COMPLETED = "COMPLETED"
    REVIEW_WAITING = "REVIEW_WAITING"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


__all__ = ["RunDisposition"]
