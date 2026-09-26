"""Shared pytest configuration for the Logstead backend.

Registers a Hypothesis default profile that runs a minimum of 100 examples per
property (per the design's requirement that property-based tests use at least
100 iterations). Set the environment variable ``HYPOTHESIS_PROFILE`` to select
a different registered profile (e.g. ``ci`` for more thorough runs).
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

settings.register_profile(
    "default",
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile("ci", max_examples=500)

settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))
