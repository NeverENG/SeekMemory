"""Deterministic long-horizon persona and relationship benchmark; production boundaries, fake provider.

确定性长周期人格与关系评测；驱动生产边界，使用假模型适配器，不访问网络。

The package is a measurement harness, not production code.  Every module here is
only imported by ``benchmarks/``, ``tests/`` and the CLI in :mod:`run`.
"""

from __future__ import annotations

# Version strings are part of the report contract.  Bumping one invalidates
# comparisons against reports produced by an older harness.
PACKAGE_VERSION = "1.0.0"
MANIFEST_SCHEMA = "seekmemory.long_horizon.manifest.v1"
REPORT_SCHEMA = "seekmemory.long_horizon.v1"
ACTOR_VERSION = "lh-actor-v1"

# The issue asks for 7/30/60/90 day checkpoints; the harness keeps them ordered.
HORIZONS = (7, 30, 60, 90)

BASELINES = ("no-memory", "rolling-summary", "seekmemory-nomaint", "seekmemory")

# Dimension keys are stable: reports and dashboards index them by name.
DIMENSIONS = (
    "memory_continuity",
    "correction_recovery",
    "emotion_trajectory",
    "role_action_coherence",
    "relationship_boundary",
    "privacy_evidence",
    "efficiency",
)

__all__ = [
    "PACKAGE_VERSION",
    "MANIFEST_SCHEMA",
    "REPORT_SCHEMA",
    "ACTOR_VERSION",
    "HORIZONS",
    "BASELINES",
    "DIMENSIONS",
]
