# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from backend.api_access.keys import generate_key, hash_key, key_prefix


def test_generate_key_format_and_uniqueness():
    a = generate_key()
    b = generate_key()
    assert a.startswith("ak_live_")
    assert a != b                      # cryptographically random
    assert len(a) >= 40                # prefix + ample entropy


def test_hash_key_is_deterministic_sha256_hex():
    h = hash_key("ak_live_example")
    assert h == hash_key("ak_live_example")
    assert len(h) == 64
    assert h == h.lower()
    assert all(c in "0123456789abcdef" for c in h)
    assert hash_key("a") != hash_key("b")


def test_key_prefix_is_first_12_chars():
    raw = "ak_live_abcdefghijklmnop"
    assert key_prefix(raw) == "ak_live_abcd"
    assert len(key_prefix(raw)) == 12
