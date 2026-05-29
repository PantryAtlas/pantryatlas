"""Bearer-token helpers for the device-trust fabric (pure, no I/O).

A device's raw token is minted once at approval and shown to the operator once;
only its sha256 hash is persisted. Verification hashes the presented bearer and
compares to the stored hash.
"""

from __future__ import annotations

import hashlib
import secrets


def mint_token() -> str:
    """Return a fresh URL-safe bearer token (~43 chars from 32 random bytes)."""
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """Return the sha256 hex digest of a raw token (what we persist + compare)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
