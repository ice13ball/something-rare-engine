# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

import db as _db
from api_access import admin_auth, admin_crud

router = APIRouter(prefix="/admin/api")

COOKIE = "abyssal_admin"
SESSION_TTL_HOURS = 12


def _client_ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


async def require_super_admin(request: Request):
    token = request.cookies.get(COOKIE)
    admin = await admin_auth.get_session_admin(_db.pool, token, datetime.now(timezone.utc))
    if admin is None or admin["role"] != "super_admin":
        raise HTTPException(401, "not authenticated")
    return admin


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response):
    now = datetime.now(timezone.utc)
    rec = await admin_auth.get_admin_by_username(_db.pool, body.username)
    # generic failure for missing user / bad password / disabled (no enumeration)
    if rec is None or rec["status"] != "active":
        raise HTTPException(401, "invalid credentials")
    locked, _ = admin_auth.lockout_state(rec["failed_logins"] or 0, rec["locked_until"], now)
    if locked:
        raise HTTPException(429, "account temporarily locked")
    if not admin_auth.verify_password(body.password, rec["password_hash"]):
        await admin_auth.register_login_result(_db.pool, rec["id"], False, now)
        raise HTTPException(401, "invalid credentials")
    await admin_auth.register_login_result(_db.pool, rec["id"], True, now)
    raw = await admin_auth.create_session(_db.pool, rec["id"], _client_ip(request), SESSION_TTL_HOURS)
    response.set_cookie(COOKIE, raw, httponly=True, samesite="strict", secure=True,
                        max_age=SESSION_TTL_HOURS * 3600, path="/admin")
    return {"ok": True, "role": rec["role"]}


@router.post("/logout")
async def logout(request: Request, response: Response, _=Depends(require_super_admin)):
    token = request.cookies.get(COOKIE)
    if token:
        await admin_auth.delete_session(_db.pool, token)
    response.delete_cookie(COOKIE, path="/admin")
    return {"ok": True}


@router.get("/me")
async def me(admin=Depends(require_super_admin)):
    return {"username": admin["username"], "role": admin["role"]}


# ── orgs ──────────────────────────────────────────────────────────────────────
class OrgBody(BaseModel):
    name: str
    contact: str | None = None
    rate_limit_per_day_cap: int | None = None
    rate_limit_per_min_cap: int | None = None
    max_keys: int | None = None
    expires_at: datetime | None = None
    notes: str | None = None


@router.get("/orgs")
async def get_orgs(_=Depends(require_super_admin)):
    return [dict(r) for r in await admin_crud.list_orgs(_db.pool)]


@router.post("/orgs")
async def post_org(body: OrgBody, _=Depends(require_super_admin)):
    oid = await admin_crud.create_org(_db.pool, **body.model_dump())
    return {"id": oid}


@router.patch("/orgs/{org_id}")
async def patch_org(org_id: int, body: dict, _=Depends(require_super_admin)):
    await admin_crud.update_org(_db.pool, org_id=org_id, **body)
    return {"ok": True}


@router.delete("/orgs/{org_id}")
async def delete_org(org_id: int, _=Depends(require_super_admin)):
    """Hard-delete an org and (via FK cascade) its keys, leak flags, and org-admins."""
    try:
        deleted = await admin_crud.delete_org(_db.pool, org_id=org_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not deleted:
        raise HTTPException(404, "organization not found")
    return {"ok": True}


class OrgAdminBody(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


@router.get("/orgs/{org_id}/admins")
async def get_org_admins(org_id: int, _=Depends(require_super_admin)):
    return [dict(r) for r in await admin_auth.list_org_admins(_db.pool, org_id)]


@router.post("/orgs/{org_id}/admins")
async def post_org_admin(org_id: int, body: OrgAdminBody, admin=Depends(require_super_admin)):
    try:
        uid = await admin_auth.create_admin_user(
            _db.pool, body.username, body.password, "org_admin", org_id, admin["username"]
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(400, "username already taken")
    except asyncpg.ForeignKeyViolationError:
        raise HTTPException(404, "organization not found")
    return {"id": uid}


@router.delete("/orgs/{org_id}/admins/{user_id}")
async def delete_org_admin(org_id: int, user_id: int, _=Depends(require_super_admin)):
    """Remove an org-admin user (their sessions cascade away)."""
    if not await admin_auth.delete_org_admin(_db.pool, org_id, user_id):
        raise HTTPException(404, "org admin not found")
    return {"ok": True}


# ── keys ──────────────────────────────────────────────────────────────────────
class KeyBody(BaseModel):
    org_id: int
    member_label: str
    rate_limit_per_day: int | None = None
    rate_limit_per_min: int | None = None
    expires_at: datetime | None = None


@router.get("/keys")
async def get_keys(org_id: int | None = None, _=Depends(require_super_admin)):
    rows = await admin_crud.list_keys(_db.pool, org_id)
    return [{k: v for k, v in dict(r).items() if k != "key_hash"} for r in rows]


@router.post("/keys")
async def post_key(body: KeyBody, admin=Depends(require_super_admin)):
    try:
        kid, raw = await admin_crud.create_key(
            _db.pool, body.org_id, body.member_label, body.rate_limit_per_day,
            body.rate_limit_per_min, body.expires_at, admin["username"],
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": kid, "key": raw}  # raw key shown ONCE


@router.patch("/keys/{key_id}")
async def patch_key(key_id: int, body: dict, _=Depends(require_super_admin)):
    await admin_crud.update_key(_db.pool, key_id=key_id, **body)
    return {"ok": True}


@router.post("/keys/{key_id}/revoke")
async def post_revoke(key_id: int, _=Depends(require_super_admin)):
    await admin_crud.revoke_key(_db.pool, key_id=key_id)
    return {"ok": True}


@router.delete("/keys/{key_id}")
async def delete_key(key_id: int, _=Depends(require_super_admin)):
    """Permanently delete a key and erase its request history (request_log,
    usage_rollup, leak_flags). Irreversible — distinct from revoke."""
    try:
        deleted = await admin_crud.delete_key(_db.pool, key_id=key_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not deleted:
        raise HTTPException(404, "key not found")
    return {"ok": True}


# ── stats ─────────────────────────────────────────────────────────────────────
@router.get("/keys/{key_id}/usage")
async def key_usage(key_id: int, _=Depends(require_super_admin)):
    async with _db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT hour, SUM(request_count) AS requests, SUM(error_count) AS errors,
                   SUM(total_bytes) AS bytes
            FROM api_access.usage_rollup WHERE key_id = $1
            GROUP BY hour ORDER BY hour DESC LIMIT 168
            """,
            key_id,
        )
        by_ep = await conn.fetch(
            """
            SELECT endpoint_label, SUM(request_count) AS requests, SUM(error_count) AS errors,
                   SUM(total_bytes) AS bytes
            FROM api_access.usage_rollup WHERE key_id = $1
            GROUP BY endpoint_label ORDER BY requests DESC LIMIT 50
            """,
            key_id,
        )
    return {"hourly": [dict(r) for r in rows], "by_endpoint": [dict(r) for r in by_ep]}


@router.get("/keys/{key_id}/sources")
async def key_sources(key_id: int, _=Depends(require_super_admin)):
    async with _db.pool.acquire() as conn:
        countries = await conn.fetch(
            "SELECT COALESCE(country,'??') AS country, COUNT(*) AS n FROM api_access.request_log "
            "WHERE key_id = $1 GROUP BY country ORDER BY n DESC LIMIT 25", key_id)
        agents = await conn.fetch(
            "SELECT COALESCE(user_agent,'(none)') AS ua, COUNT(*) AS n FROM api_access.request_log "
            "WHERE key_id = $1 GROUP BY user_agent ORDER BY n DESC LIMIT 25", key_id)
    return {"countries": [dict(r) for r in countries], "user_agents": [dict(r) for r in agents]}


@router.get("/overview")
async def overview(_=Depends(require_super_admin)):
    async with _db.pool.acquire() as conn:
        orgs = await conn.fetchval("SELECT COUNT(*) FROM api_access.organizations")
        keys = await conn.fetchval("SELECT COUNT(*) FROM api_access.api_keys WHERE status='active'")
        last24 = await conn.fetchval(
            "SELECT COUNT(*) FROM api_access.request_log WHERE ts > NOW() - INTERVAL '24 hours'")
    return {"orgs": orgs, "active_keys": keys, "requests_24h": last24}


@router.get("/usage-series")
async def usage_series(_=Depends(require_super_admin)):
    """Hourly request/error totals across all keys for the last 7 days (dashboard chart)."""
    async with _db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT hour, SUM(request_count) AS requests, SUM(error_count) AS errors
            FROM api_access.usage_rollup
            WHERE hour > NOW() - INTERVAL '7 days'
            GROUP BY hour ORDER BY hour
            """
        )
    return [dict(r) for r in rows]


@router.get("/errors")
async def error_log(hours: int = 168, limit: int = 200, admin=Depends(require_super_admin)):
    """Recent HTTP error requests (status >= 400): a grouped summary + a raw recent tail."""
    hours = max(1, min(hours, 2160))  # up to 90d (retention)
    limit = max(1, min(limit, 1000))
    async with _db.pool.acquire() as conn:
        summary = await conn.fetch(
            """
            SELECT status_code, method, path, count(*) AS n, max(ts) AS latest
            FROM api_access.request_log
            WHERE status_code >= 400 AND ts > now() - make_interval(hours => $1)
            GROUP BY status_code, method, path
            ORDER BY n DESC, latest DESC
            LIMIT 100
            """,
            hours,
        )
        recent = await conn.fetch(
            """
            SELECT ts, status_code, method, path, ip, user_agent, org_id, key_id
            FROM api_access.request_log
            WHERE status_code >= 400 AND ts > now() - make_interval(hours => $1)
            ORDER BY ts DESC
            LIMIT $2
            """,
            hours, limit,
        )
    return {
        "window_hours": hours,
        "summary": [
            {"status_code": r["status_code"], "method": r["method"], "path": r["path"],
             "n": r["n"], "latest": r["latest"].isoformat() if r["latest"] else None}
            for r in summary
        ],
        "recent": [
            {"ts": r["ts"].isoformat() if r["ts"] else None, "status_code": r["status_code"],
             "method": r["method"], "path": r["path"], "ip": r["ip"],
             "user_agent": r["user_agent"], "org_id": r["org_id"], "key_id": r["key_id"]}
            for r in recent
        ],
    }


# ── leak flags ────────────────────────────────────────────────────────────────

@router.get("/flags")
async def get_flags(_=Depends(require_super_admin)):
    """All active (unacknowledged) leak flags across every org, newest first."""
    async with _db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT f.id, f.key_id, f.flag_type, f.detail, f.severity, f.detected_at,
                   k.member_label, o.name AS org_name
            FROM api_access.leak_flags f
            JOIN api_access.api_keys k ON k.id = f.key_id
            JOIN api_access.organizations o ON o.id = k.org_id
            WHERE f.acknowledged_at IS NULL
            ORDER BY f.detected_at DESC
            """
        )
    return [dict(r) for r in rows]


@router.post("/flags/{flag_id}/ack")
async def ack_flag(flag_id: int, _=Depends(require_super_admin)):
    async with _db.pool.acquire() as conn:
        status = await conn.execute(
            "UPDATE api_access.leak_flags SET acknowledged_at = NOW() WHERE id = $1", flag_id
        )
    if status.split()[-1] == "0":
        raise HTTPException(404, "flag not found")
    return {"ok": True}
