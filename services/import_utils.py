"""Small bounded work helpers shared by the import validator and runner."""

from __future__ import annotations

import itertools

VALIDATION_BATCH = 500


def take(iterator, limit: int):
    """Read one bounded batch from an iterator."""
    return list(itertools.islice(iterator, max(1, int(limit))))
