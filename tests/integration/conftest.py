"""Pytest configuration for integration tests.

Auto-skips pi_integration marked tests unless PANTRYATLAS_PI_INTEGRATION=1.
"""
import os

import pytest


def pytest_collection_modifyitems(config, items):
    """Skip pi_integration tests by default unless opt-in env var is set."""
    if os.environ.get("PANTRYATLAS_PI_INTEGRATION") == "1":
        return  # don't skip — run them
    skip_marker = pytest.mark.skip(reason="PANTRYATLAS_PI_INTEGRATION not set")
    for item in items:
        if "pi_integration" in item.keywords:
            item.add_marker(skip_marker)
