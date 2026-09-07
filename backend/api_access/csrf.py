# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import secrets


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_ok(cookie_val: str | None, header_val: str | None) -> bool:
    if not cookie_val or not header_val:
        return False
    return secrets.compare_digest(cookie_val, header_val)
