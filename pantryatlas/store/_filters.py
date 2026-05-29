"""Shared validation for ``query_by_vector`` metadata filters.

v0.2 supports only exact-match scalar **string** filters on known metadata
columns (e.g. ``{"language": "en"}``). Lists, ranges, and non-string values are
rejected explicitly rather than silently coerced.
"""

from __future__ import annotations


def validate_scalar_filters(filters: dict, allowed: set[str]) -> None:
    """Validate a metadata-filter dict.

    Args:
        filters: The caller-supplied ``{column: value}`` mapping.
        allowed: The set of filterable column names for this store.

    Raises:
        ValueError: If a key is not in ``allowed`` or a value is not a ``str``.
    """
    unknown = set(filters) - allowed
    if unknown:
        raise ValueError(
            f"unsupported filter keys: {sorted(unknown)}; allowed: {sorted(allowed)}"
        )
    for key, value in filters.items():
        if not isinstance(value, str):
            raise ValueError(
                f"filter '{key}' must be a string scalar, got {type(value).__name__}"
            )
