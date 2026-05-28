"""Tests for pantryatlas.geometry.slerp — AC-3 through AC-8."""

from __future__ import annotations

import numpy as np
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pantryatlas.geometry.slerp import constrained_slerp, slerp

# ---------------------------------------------------------------------------
# Hypothesis strategy helpers
# ---------------------------------------------------------------------------


@st.composite
def unit_vector(draw, dim: int = 1024):
    """Draw a unit-norm vector of the given dimension."""
    raw = draw(
        st.lists(
            st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False),
            min_size=dim,
            max_size=dim,
        )
    )
    v = np.array(raw, dtype=np.float64)
    n = np.linalg.norm(v)
    if n < 1e-9:
        result = np.zeros(dim, dtype=np.float64)
        result[0] = 1.0
        return result
    return v / n


# ---------------------------------------------------------------------------
# Reference implementation (textbook, used only for cross-checking)
# ---------------------------------------------------------------------------


def _reference_slerp(
    a: np.ndarray,
    b: np.ndarray,
    t: float,
) -> np.ndarray:
    """Textbook SLERP for cross-checking the production implementation."""
    dot = np.clip(np.dot(a, b), -1.0, 1.0)
    omega = np.arccos(dot)
    sin_omega = np.sin(omega)
    if sin_omega < 1e-9:
        out = a + t * (b - a)
        n = np.linalg.norm(out)
        if n < 1e-9:
            return a.copy()
        return out / n
    return (np.sin((1.0 - t) * omega) / sin_omega) * a + (np.sin(t * omega) / sin_omega) * b


# ---------------------------------------------------------------------------
# AC-4 — 1000 hypothesis examples vs reference
# ---------------------------------------------------------------------------


@given(
    a=unit_vector(dim=64),
    b=unit_vector(dim=64),
    t=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@settings(max_examples=1000, suppress_health_check=[HealthCheck.too_slow])
def test_matches_reference(a, b, t):
    """slerp(a, b, t) must match the reference implementation within 1e-6."""
    out = slerp(a, b, t)
    ref = _reference_slerp(a, b, t)
    np.testing.assert_allclose(out, ref, atol=1e-6)


# ---------------------------------------------------------------------------
# AC-5 — dot≈1 edge: slerp(a, a, 0.5) must not return NaN
# ---------------------------------------------------------------------------


def test_identical_endpoints_no_nan():
    """slerp(a, a, 0.5) must return a without any NaN values."""
    a = np.array([1.0, 0.0, 0.0])
    out = slerp(a, a, 0.5)
    assert not np.any(np.isnan(out)), f"Got NaN in output: {out}"
    np.testing.assert_allclose(out, a, atol=1e-6)


# ---------------------------------------------------------------------------
# AC-6 — unit norm preserved
# ---------------------------------------------------------------------------


@given(
    a=unit_vector(dim=32),
    b=unit_vector(dim=32),
    t=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_unit_norm_preserved(a, b, t):
    """Output of slerp must remain unit-norm for any unit a, b and t in [0,1]."""
    out = slerp(a, b, t)
    assert abs(np.linalg.norm(out) - 1.0) < 1e-6, (
        f"Norm deviated: {np.linalg.norm(out):.9f}"
    )


# ---------------------------------------------------------------------------
# AC-7 — endpoint identity: slerp(a, b, 0) == a, slerp(a, b, 1) == b
# ---------------------------------------------------------------------------


@given(
    a=unit_vector(dim=32),
    b=unit_vector(dim=32),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_endpoint_identity(a, b):
    """slerp(a, b, 0) must equal a and slerp(a, b, 1) must equal b."""
    np.testing.assert_allclose(slerp(a, b, 0.0), a, atol=1e-6)
    np.testing.assert_allclose(slerp(a, b, 1.0), b, atol=1e-6)


# ---------------------------------------------------------------------------
# AC-8 — constrained_slerp preserves mode projection
# ---------------------------------------------------------------------------


@given(
    a=unit_vector(dim=32),
    b=unit_vector(dim=32),
    m=unit_vector(dim=32),
    t=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_constrained_preserves_mode_projection(a, b, m, t):
    """constrained_slerp result must have projection onto m >= a's projection."""
    out = constrained_slerp(a, b, t, m)
    a_proj = float(np.dot(a, m))
    out_proj = float(np.dot(out, m))
    assert out_proj >= a_proj - 1e-9, (
        f"constrained_slerp dropped below mode projection: "
        f"a.dot(m)={a_proj:.6f}, out.dot(m)={out_proj:.6f}"
    )
