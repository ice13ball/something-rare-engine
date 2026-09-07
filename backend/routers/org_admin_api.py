# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

# backend/routers/org_admin_api.py
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

import db as _db
from api_access import admin_auth, csrf, org_crud

router = APIRouter(prefix="/org-admin/api")

COOKIE = "abyssal_org"
CSRF_COOKIE = "csrf_org"
SESSION_TTL_HOURS = 8
COOKIE_PATH = "/org-admin"


def _client_ip(request: Request) -> str | None:
    # Trust ONLY the proxy-set X-Real-IP, which nginx overwrites per request with the
    # resolved client address. The raw X-Forwarded-For left-most value is supplied by
    # the client and is spoofable, so it is deliberately NOT used here. Fall back to
    # the socket peer when no trusted header is present.
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else None


async def require_org_admin(request: Request):
    token = request.cookies.get(COOKIE)
    admin = await admin_auth.get_session_admin(_db.pool, token, datetime.now(timezone.utc))
    if admin is None or admin["role"] != "org_admin" or admin["org_id"] is None:
        raise HTTPException(401, "not authenticated")
    return admin


async def require_csrf(request: Request):
    if not csrf.csrf_ok(request.cookies.get(CSRF_COOKIE),
                        request.headers.get("x-csrf-token")):
        raise HTTPException(403, "csrf check failed")


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    now = datetime.now(timezone.utc)
    rec = await admin_auth.get_admin_by_username(_db.pool, body.username)
    eligible = rec is not None and rec["status"] == "active" and rec["role"] == "org_admin"
    locked = False
    if eligible:
        locked, _ = admin_auth.lockout_state(rec["failed_logins"] or 0, rec["locked_until"], now)
    # Always run exactly one bcrypt verification so unknown / disabled / wrong-role /
    # locked usernames cost the same as a real password check — no enumeration via
    # response latency.
    if eligible and not locked:
        password_ok = admin_auth.verify_password(body.password, rec["password_hash"])
    else:
        admin_auth.dummy_verify(body.password)
        password_ok = False
    if not (eligible and not locked and password_ok):
        # Only a real, active, non-locked org_admin with a wrong password accrues a
        # failed-login (and may trip the lockout); we never extend a lock or touch
        # non-existent users.
        if eligible and not locked:
            await admin_auth.register_login_result(_db.pool, rec["id"], False, now)
        # Uniform response for every failure mode (missing user / disabled / wrong
        # role / locked / bad password) — no status-code or message oracle. Account
        # lockout still blocks server-side but is indistinguishable to the client.
        raise HTTPException(401, "invalid credentials")
    await admin_auth.register_login_result(_db.pool, rec["id"], True, now)
    raw = await admin_auth.create_session(_db.pool, rec["id"], _client_ip(request), SESSION_TTL_HOURS)
    token = csrf.new_csrf_token()
    common = dict(max_age=SESSION_TTL_HOURS * 3600, samesite="strict", secure=True)
    # Session cookie is httponly + scoped to the API path (never read by JS).
    response.set_cookie(COOKIE, raw, httponly=True, path=COOKIE_PATH, **common)
    # CSRF is a non-secret double-submit token the SPA (served at /org-ui/) must
    # read via document.cookie AND have sent to /org-admin/api — only path="/"
    # satisfies both. Clear any legacy /org-admin-scoped copy first to avoid a
    # duplicate-name cookie shadowing the readable one.
    response.delete_cookie(CSRF_COOKIE, path=COOKIE_PATH)
    response.set_cookie(CSRF_COOKIE, token, httponly=False, path="/", **common)
    return {"ok": True, "role": rec["role"], "org_id": rec["org_id"]}


@router.post("/logout")
async def logout(request: Request, response: Response,
                 _=Depends(require_org_admin), _c=Depends(require_csrf)):
    token = request.cookies.get(COOKIE)
    if token:
        await admin_auth.delete_session(_db.pool, token)
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path=COOKIE_PATH)  # also clear any legacy copy
    return {"ok": True}


@router.post("/revoke-sessions")
async def revoke_sessions(response: Response,
                         admin=Depends(require_org_admin), _c=Depends(require_csrf)):
    """Sign out everywhere: revoke ALL of this admin's sessions (including the caller's).
    The caller's cookies are cleared in the response, so the SPA must redirect to login."""
    n = await admin_auth.delete_all_sessions(_db.pool, admin["id"])
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path=COOKIE_PATH)  # also clear any legacy copy
    return {"ok": True, "revoked": n}


@router.get("/me")
async def me(admin=Depends(require_org_admin)):
    return {"username": admin["username"], "role": admin["role"], "org_id": admin["org_id"]}


class PasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/change-password")
async def change_password(body: PasswordBody, request: Request,
                          admin=Depends(require_org_admin), _c=Depends(require_csrf)):
    if not admin_auth.verify_password(body.current_password, admin["password_hash"]):
        raise HTTPException(400, "current password is incorrect")
    if body.new_password == body.current_password:
        raise HTTPException(400, "new password must be different from the current one")
    await admin_auth.update_admin_password(_db.pool, admin["id"], body.new_password)
    # keep this session, revoke the user's other sessions
    await admin_auth.delete_other_sessions(_db.pool, admin["id"], request.cookies.get(COOKIE))
    return {"ok": True}


@router.get("/keys")
async def get_keys(admin=Depends(require_org_admin)):
    rows = await org_crud.list_keys_for_org(_db.pool, admin["org_id"])
    return [{k: v for k, v in dict(r).items() if k != "key_hash"} for r in rows]


class KeyBody(BaseModel):
    member_label: str = Field(min_length=1, max_length=200)
    rate_limit_per_day: int | None = Field(default=None, ge=1)
    rate_limit_per_min: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None


@router.post("/keys")
async def post_key(body: KeyBody, admin=Depends(require_org_admin), _c=Depends(require_csrf)):
    try:
        kid, raw = await org_crud.create_key_for_org(
            _db.pool, admin["org_id"], body.member_label, body.rate_limit_per_day,
            body.rate_limit_per_min, body.expires_at, admin["username"],
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": kid, "key": raw}


class KeyPatchBody(BaseModel):
    member_label: str | None = Field(default=None, min_length=1, max_length=200)
    rate_limit_per_day: int | None = Field(default=None, ge=1)
    rate_limit_per_min: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)


@router.patch("/keys/{key_id}")
async def patch_key(key_id: int, body: KeyPatchBody, admin=Depends(require_org_admin), _c=Depends(require_csrf)):
    fields = body.model_dump(exclude_unset=True)
    ok = await org_crud.update_key_in_org(_db.pool, org_id=admin["org_id"], key_id=key_id, **fields)
    if not ok:
        raise HTTPException(404, "key not found")
    return {"ok": True}


@router.post("/keys/{key_id}/revoke")
async def post_revoke(key_id: int, admin=Depends(require_org_admin), _c=Depends(require_csrf)):
    if not await org_crud.revoke_key_in_org(_db.pool, org_id=admin["org_id"], key_id=key_id):
        raise HTTPException(404, "key not found")
    return {"ok": True}


@router.get("/keys/{key_id}/usage")
async def key_usage(key_id: int, admin=Depends(require_org_admin)):
    res = await org_crud.usage_for_key_in_org(_db.pool, admin["org_id"], key_id)
    if res is None:
        raise HTTPException(404, "key not found")
    return res


@router.get("/keys/{key_id}/sources")
async def key_sources(key_id: int, admin=Depends(require_org_admin)):
    res = await org_crud.sources_for_key_in_org(_db.pool, admin["org_id"], key_id)
    if res is None:
        raise HTTPException(404, "key not found")
    return res


@router.get("/flags")
async def get_flags(admin=Depends(require_org_admin)):
    return [dict(r) for r in await org_crud.list_flags_for_org(_db.pool, admin["org_id"])]


@router.post("/flags/{flag_id}/ack")
async def ack_flag(flag_id: int, admin=Depends(require_org_admin), _c=Depends(require_csrf)):
    if not await org_crud.ack_flag_in_org(_db.pool, org_id=admin["org_id"], flag_id=flag_id):
        raise HTTPException(404, "flag not found")
    return {"ok": True}
