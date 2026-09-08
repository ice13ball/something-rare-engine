# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import hmac
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException, Request, Security
from fastapi.security.api_key import APIKeyHeader

from api_access.auth import resolve_and_check

_header = APIKeyHeader(name="X-API-Key", auto_error=True)


async def get_api_key(request: Request, key: str = Security(_header)) -> str:
    """Validate X-API-Key against the DB-backed key cache (env fallback for the
    frontend). Stashes the resolved key/org id on request.state for logging.
    """
    decision, record = await resolve_and_check(key)
    if decision.allowed:
        request.state.api_key_id = record.id if record else None
        request.state.api_org_id = record.org_id if record else None
        return key
    msg = "Rate limit exceeded" if decision.status_code == 429 else "Invalid API key"
    raise HTTPException(decision.status_code, msg)


# ── Admin dashboard token ───────────────────────────────────────────────────
# Moved out of main.py (Task 3 of the backend vertical-split refactor) together
# with `require_admin_token`, which reads this module global at call time.
# `backend/routers/admin_layers_api.py`'s token-rotation endpoint rebinds
# `auth.ADMIN_DASHBOARD_TOKEN` at runtime — it MUST target this module, not
# `main`, or rotation silently keeps accepting the old token. Set
# ADMIN_DASHBOARD_TOKEN in the VPS systemd env — never commit to git.
#
# Load backend/.env before reading the token. `auth` is imported by main.py long
# before main.py's own load_dotenv() runs, so without this the token would be ""
# on any path that depends on dotenv rather than a pre-populated process env
# (systemd sets EnvironmentFile in production, which is why this is invisible there).
# load_dotenv does not override variables already present in the environment,
# so this is safe and idempotent.
load_dotenv(Path(__file__).resolve().parent / ".env")

def load_admin_token() -> str:
    # Runtime state is separate from .env: the deploy user sources .env as shell
    # code, so a service allowed to rewrite it could escape its Unix account.
    token_file = os.getenv("ADMIN_DASHBOARD_TOKEN_FILE")
    if token_file:
        return Path(token_file).read_text().strip()  # fail closed on bad deployment
    return os.getenv("ADMIN_DASHBOARD_TOKEN", "")


ADMIN_DASHBOARD_TOKEN = load_admin_token()


async def require_admin_token(request: Request, token: str = "") -> None:
    """Single choke point for every admin-token check in the backend.

    Prefers the `X-Admin-Token` header; the `token` query parameter is kept
    only as a deprecated fallback (query strings land in access logs, proxy
    logs and browser history — avoid it in new integrations). Comparison is
    constant-time (`hmac.compare_digest`) so a wrong guess can't be narrowed
    down byte-by-byte via response timing; the "is it configured at all"
    check stays an ordinary comparison since `compare_digest` raises on an
    empty/unset token. Both sides are encoded to bytes first: comparing str
    values raises TypeError as soon as either holds a non-ASCII character.
    """
    supplied = request.headers.get("X-Admin-Token", "") or token
    # .encode(): compare_digest raises TypeError on str with any non-ASCII
    # character, which would turn a token containing one into a 500 instead of
    # a 403. Bytes have no such restriction.
    if not ADMIN_DASHBOARD_TOKEN or not supplied or not hmac.compare_digest(
        supplied.encode(), ADMIN_DASHBOARD_TOKEN.encode()
    ):
        raise HTTPException(status_code=403, detail="Forbidden")
