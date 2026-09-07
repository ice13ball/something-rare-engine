# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Cookie-authed CRUD for startup_profiles. Mirrors admin_layers_api.py."""
from __future__ import annotations
import json
import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import db as _db
from routers.admin_api import require_super_admin
import audit
import profiles as _profiles

router = APIRouter(prefix="/admin/api", dependencies=[Depends(require_super_admin)])


class _ProfileBody(BaseModel):
    id: str
    section: str = "ocean"
    order_idx: int = 100
    layers: list[str] = []
    label: dict = {}
    description: dict = {}
    accent: str | None = None
    views: dict = {}


class _PatchBody(BaseModel):
    section: str | None = None
    order_idx: int | None = None
    status: str | None = None
    layers: list[str] | None = None
    label: dict | None = None
    description: dict | None = None
    accent: str | None = None
    views: dict | None = None


class _ReorderBody(BaseModel):
    order: list[str]  # profile ids in desired order


def _validate_body(b: _ProfileBody) -> None:
    _profiles.validate_profile(b.model_dump(), _profiles.KNOWN_LAYER_IDS)


def _bust() -> None:
    import main  # lazy — main imports this router at load time
    main._bust_profiles_cache()


@router.get("/profiles")
async def list_profiles():
    async with _db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, section, order_idx, status, layers, label, description, accent, views, "
            "updated_at, updated_by FROM startup_profiles ORDER BY section, order_idx")
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "section": r["section"], "order_idx": r["order_idx"],
            "status": r["status"], "layers": list(r["layers"]),
            "label": json.loads(r["label"]) if isinstance(r["label"], str) else r["label"],
            "description": json.loads(r["description"]) if isinstance(r["description"], str) else r["description"],
            "accent": r["accent"],
            "views": json.loads(r["views"]) if isinstance(r["views"], str) else (r["views"] or {}),
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            "updated_by": r["updated_by"],
        })
    return out


@router.post("/profiles")
async def create_profile(body: _ProfileBody, admin=Depends(require_super_admin)):
    try:
        _validate_body(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    async with _db.pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM startup_profiles WHERE id=$1", body.id)
        if exists:
            raise HTTPException(409, f"profile {body.id!r} already exists")
        sv = _profiles.sanitize_views(body.views, body.layers)
        try:
            async with conn.transaction():
                await conn.execute(
                    """INSERT INTO startup_profiles
                         (id, section, order_idx, status, layers, label, description, accent, views, updated_by)
                       VALUES ($1,$2,$3,'enabled',$4,$5::jsonb,$6::jsonb,$7,$8::jsonb,$9)""",
                    body.id, body.section, body.order_idx, body.layers,
                    json.dumps(body.label), json.dumps(body.description), body.accent,
                    json.dumps(sv), admin["username"])
                await audit.write_audit(conn, admin["username"], "profile_create", body.id,
                                        {"section": body.section, "layers": body.layers})
        except asyncpg.UniqueViolationError:
            raise HTTPException(409, f"profile {body.id!r} already exists")
    _bust()
    return {"ok": True, "id": body.id}


@router.patch("/profiles/{profile_id}")
async def patch_profile(profile_id: str, body: _PatchBody, admin=Depends(require_super_admin)):
    async with _db.pool.acquire() as conn:
        cur = await conn.fetchrow("SELECT * FROM startup_profiles WHERE id=$1", profile_id)
        if cur is None:
            raise HTTPException(404, f"unknown profile {profile_id!r}")
        merged = {
            "id": profile_id,
            "section": body.section if body.section is not None else cur["section"],
            "order_idx": body.order_idx if body.order_idx is not None else cur["order_idx"],
            "layers": body.layers if body.layers is not None else list(cur["layers"]),
            "label": body.label if body.label is not None else (
                json.loads(cur["label"]) if isinstance(cur["label"], str) else cur["label"]),
            "description": body.description if body.description is not None else (
                json.loads(cur["description"]) if isinstance(cur["description"], str) else cur["description"]),
            "accent": body.accent if body.accent is not None else cur["accent"],
            "views": body.views if body.views is not None else (
                json.loads(cur["views"]) if isinstance(cur["views"], str) else (cur["views"] or {})),
        }
        try:
            _profiles.validate_profile(merged, _profiles.KNOWN_LAYER_IDS)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if body.status is not None and body.status not in ("enabled", "disabled"):
            raise HTTPException(400, "status must be 'enabled' or 'disabled'")
        new_status = body.status if body.status is not None else cur["status"]
        sv = _profiles.sanitize_views(merged["views"], merged["layers"])
        async with conn.transaction():
            await conn.execute(
                """UPDATE startup_profiles SET section=$2, order_idx=$3, status=$4,
                     layers=$5, label=$6::jsonb, description=$7::jsonb, accent=$8,
                     views=$9::jsonb, updated_at=now(), updated_by=$10 WHERE id=$1""",
                profile_id, merged["section"], merged["order_idx"], new_status,
                merged["layers"], json.dumps(merged["label"]),
                json.dumps(merged["description"]), merged["accent"],
                json.dumps(sv), admin["username"])
            await audit.write_audit(conn, admin["username"], "profile_patch", profile_id,
                                    {"status": new_status, "layers": merged["layers"]})
    _bust()
    return {"ok": True, "id": profile_id}


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str, admin=Depends(require_super_admin)):
    async with _db.pool.acquire() as conn:
        found = await conn.fetchval("SELECT 1 FROM startup_profiles WHERE id=$1", profile_id)
        if not found:
            raise HTTPException(404, f"unknown profile {profile_id!r}")
        async with conn.transaction():
            await conn.execute("DELETE FROM startup_profiles WHERE id=$1", profile_id)
            await audit.write_audit(conn, admin["username"], "profile_delete", profile_id, None)
    _bust()
    return {"ok": True, "id": profile_id}


@router.post("/profiles/reorder")
async def reorder_profiles(body: _ReorderBody, admin=Depends(require_super_admin)):
    async with _db.pool.acquire() as conn:
        async with conn.transaction():
            for idx, pid in enumerate(body.order):
                await conn.execute(
                    "UPDATE startup_profiles SET order_idx=$2, updated_at=now(), updated_by=$3 WHERE id=$1",
                    pid, (idx + 1) * 10, admin["username"])
            await audit.write_audit(conn, admin["username"], "profile_reorder", None,
                                    {"order": body.order})
    _bust()
    return {"ok": True}
