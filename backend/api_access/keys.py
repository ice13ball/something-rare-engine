# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import hashlib
import secrets

_PREFIX = "ak_live_"
_PREFIX_DISPLAY_LEN = 12  # chars of the raw key kept for display (includes _PREFIX)


def generate_key() -> str:
    """Return a new opaque API key: 'ak_live_' + 40 URL-safe random chars.

    Only ever returned to the operator once at creation; the DB stores hash_key()
    of this value, never the raw string.
    """
    return _PREFIX + secrets.token_urlsafe(30)  # token_urlsafe(30) -> 40 chars


def hash_key(raw: str) -> str:
    """SHA-256 hex digest of the raw key. The only form persisted in the DB."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def key_prefix(raw: str) -> str:
    """First 12 chars of the raw key, stored for display (e.g. 'ak_live_ab12')."""
    return raw[:_PREFIX_DISPLAY_LEN]
