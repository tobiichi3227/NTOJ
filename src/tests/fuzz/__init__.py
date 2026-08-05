"""Shared Hypothesis profiles for TOJ fuzz and property tests."""

import os

from hypothesis import settings


settings.register_profile(
    "ci",
    max_examples=200,
    deadline=500,
    derandomize=True,
    print_blob=True,
)
settings.register_profile(
    "nightly",
    max_examples=5_000,
    deadline=None,
    print_blob=True,
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
