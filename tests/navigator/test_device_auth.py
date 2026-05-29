from __future__ import annotations

from pantryatlas.navigator.device_auth import hash_token, mint_token


def test_mint_token_is_unique_and_urlsafe():
    a, b = mint_token(), mint_token()
    assert a != b
    assert len(a) >= 32
    assert all(c.isalnum() or c in "-_" for c in a)


def test_hash_token_is_deterministic_sha256_hex():
    h1 = hash_token("abc")
    h2 = hash_token("abc")
    assert h1 == h2
    assert len(h1) == 64 and all(c in "0123456789abcdef" for c in h1)
    assert hash_token("abc") != hash_token("abd")
