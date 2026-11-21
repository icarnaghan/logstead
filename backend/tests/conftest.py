"""Shared pytest configuration for the Logstead backend.

Registers a Hypothesis default profile that runs a minimum of 100 examples per
property (per the design's requirement that property-based tests use at least
100 iterations). Set the environment variable ``HYPOTHESIS_PROFILE`` to select
a different registered profile (e.g. ``ci`` for more thorough runs).

``HYPOTHESIS_MAX_EXAMPLES`` caps ``max_examples`` for every property test,
including tests that set their own value with ``@settings``. Merge request
pipelines use it (with the ``quick`` profile) to keep the job within the runner
timeout; the full example counts still run on the default branch and on the
weekly schedule. Leave it unset locally.
"""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

# Hermetic AWS defaults. Lambda always sets a region, and developer machines
# usually have one in ~/.aws/config, but CI containers have neither, so boto3
# raised NoRegionError in tests that build a client outside moto. setdefault
# keeps any value already in the environment; the fake credentials stop a test
# from reaching a real account if moto is not active.
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

settings.register_profile(
    "default",
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile("ci", max_examples=500)
# Merge request gate: fewer, deterministic examples (see HYPOTHESIS_MAX_EXAMPLES).
settings.register_profile(
    "quick",
    max_examples=15,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)

settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


def _max_examples_cap() -> int | None:
    raw = os.environ.get("HYPOTHESIS_MAX_EXAMPLES", "").strip()
    if not raw:
        return None
    cap = int(raw)
    if cap < 1:
        raise ValueError("HYPOTHESIS_MAX_EXAMPLES must be a positive integer")
    return cap


def pytest_collection_modifyitems(config, items) -> None:
    """Apply ``HYPOTHESIS_MAX_EXAMPLES`` to tests with their own ``@settings``.

    Hypothesis reads ``_hypothesis_internal_use_settings`` from the wrapped test
    each time it runs, so lowering ``max_examples`` there takes effect without
    editing every test. Tests already at or below the cap are left alone.
    """
    cap = _max_examples_cap()
    if cap is None:
        return
    seen: set[int] = set()
    for item in items:
        test = getattr(item, "obj", None)
        current = getattr(test, "_hypothesis_internal_use_settings", None)
        if current is None or id(test) in seen:
            continue
        seen.add(id(test))
        if current.max_examples > cap:
            test._hypothesis_internal_use_settings = settings(
                current, max_examples=cap
            )
