"""SLERP and constrained SLERP utilities in pure NumPy.

Both functions operate on unit-norm vectors of arbitrary dimension.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

# Threshold below which sin(omega) is treated as "parallel enough" to skip
# the standard SLERP formula and fall back to linear interpolation.
_SIN_EPS = 1e-9


def slerp(
    a: NDArray[np.float64],
    b: NDArray[np.float64],
    t: float,
) -> NDArray[np.float64]:
    """Spherical linear interpolation between two unit vectors.

    Parameters
    ----------
    a:
        Start unit vector (any dimension).  Will be cast to float64.
    b:
        End unit vector, same shape as ``a``.
    t:
        Interpolation parameter in [0, 1].  t=0 → a, t=1 → b.

    Returns
    -------
    NDArray[np.float64]
        Unit-norm vector interpolated along the great circle from ``a`` to ``b``.

    Notes
    -----
    The ``dot ≈ 1`` (parallel) case short-circuits to linear interpolation
    followed by renormalization to avoid ``acos(1+eps) → NaN``.

    The ``dot ≈ -1`` (antiparallel) case is also caught by the same
    ``sin(omega) < EPS`` guard.  For antiparallel inputs the linear
    interpolation passes through the origin at t=0.5 (norm → 0) and then
    renormalizes to an arbitrary direction — this is geometrically undefined
    and not expected in normal use (embedding vectors are typically
    co-directional).  The function will not raise, but the result is
    implementation-defined for antiparallel inputs.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)

    dot = np.clip(np.dot(a, b), -1.0, 1.0)
    omega = np.arccos(dot)
    sin_omega = np.sin(omega)

    if sin_omega < _SIN_EPS:
        # a ≈ b (or a ≈ -b): linear interpolation + renormalize.
        out = a + t * (b - a)
        norm = np.linalg.norm(out)
        if norm < _SIN_EPS:
            # Degenerate: exactly antiparallel at t=0.5; return a as fallback.
            return a.copy()
        return out / norm

    coeff_a = np.sin((1.0 - t) * omega) / sin_omega
    coeff_b = np.sin(t * omega) / sin_omega
    return coeff_a * a + coeff_b * b


def constrained_slerp(
    a: NDArray[np.float64],
    b: NDArray[np.float64],
    t: float,
    mode_basis: NDArray[np.float64],
    *,
    tol: float = 1e-9,
) -> NDArray[np.float64]:
    """SLERP that keeps the result within the mode half-space.

    Rotates from ``a`` toward ``b`` by fraction ``t``, then — if the raw
    SLERP result drops below ``a``'s projection onto ``mode_basis`` —
    reconstructs the result analytically in the span{mode_basis, raw_perp}
    so that ``result.dot(mode_basis) == a.dot(mode_basis)`` exactly.

    Parameters
    ----------
    a:
        Start unit vector.
    b:
        End unit vector, same shape as ``a``.
    t:
        Interpolation parameter in [0, 1].
    mode_basis:
        Direction vector defining the mode half-space.  Need not be unit-norm;
        it is normalized internally.
    tol:
        Tolerance for the projection comparison.

    Returns
    -------
    NDArray[np.float64]
        Unit-norm vector that satisfies ``result.dot(mode_basis) >= a.dot(mode_basis) - tol``.

    Notes
    -----
    When the raw SLERP output satisfies the constraint, it is returned unchanged.
    Otherwise the result is constructed as::

        result = a_proj * m̂ + sqrt(1 - a_proj²) * (raw_perp / |raw_perp|)

    where ``raw_perp = raw - raw.dot(m̂) * m̂`` is the component of ``raw``
    orthogonal to ``mode_basis``.  This gives ``result.dot(m̂) = a_proj``
    exactly and ``|result| = 1`` exactly (up to float64 rounding), and works
    correctly even when ``a_proj = 1`` (the perp coefficient is zero →
    ``result = m̂``).

    Edge case: if ``|raw_perp|`` is negligible (``raw ≈ ±m̂``) and the
    constraint is violated, fall back to returning ``a`` — it trivially satisfies
    the constraint and this situation is geometrically degenerate.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    mode_basis = np.asarray(mode_basis, dtype=np.float64)

    # Normalize mode_basis.
    mb_norm = np.linalg.norm(mode_basis)
    if mb_norm > _SIN_EPS:
        mode_basis = mode_basis / mb_norm

    raw = slerp(a, b, t)
    a_proj = float(np.dot(a, mode_basis))

    # Fast path: constraint already satisfied.
    raw_proj = float(np.dot(raw, mode_basis))
    if raw_proj >= a_proj - tol:
        return raw

    # Analytical reconstruction in span{mode_basis, raw_perp}.
    # raw_perp is the component of raw orthogonal to mode_basis.
    raw_perp = raw - raw_proj * mode_basis
    perp_norm = float(np.linalg.norm(raw_perp))

    if perp_norm < _SIN_EPS:
        # raw is nearly parallel or antiparallel to mode_basis and the
        # constraint is violated. Geometrically degenerate — fall back to a.
        return a.copy()

    # Clip a_proj to [-1, 1] to guard against fp drift before sqrt.
    a_proj_clipped = float(np.clip(a_proj, -1.0, 1.0))
    perp_coeff = float(np.sqrt(max(0.0, 1.0 - a_proj_clipped ** 2)))

    result = a_proj_clipped * mode_basis + perp_coeff * (raw_perp / perp_norm)

    # Defensive renormalization (should be near-unity already).
    result_norm = np.linalg.norm(result)
    if result_norm > _SIN_EPS:
        result = result / result_norm

    return result
