# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import db as _db
from routers.admin_api import require_super_admin  # reuse cookie auth
import layer_ops
import audit
from sync_log import is_sync_paused, invalidate_paused_cache

router = APIRouter(prefix="/admin/api", dependencies=[Depends(require_super_admin)])


def _bust_layer_cache() -> None:
    """Reset main.py's public /v1/map/layer-config cache after any config change."""
    import main  # lazy — main imports this router at load time
    main._layer_config_cache = None
    main._layer_config_cache_ts = 0.0


class _StatusBody(BaseModel):
    status: str


class _PatchBody(BaseModel):
    order_idx: int | None = None
    default_on: bool | None = None
    modes: list[str] | None = None


@router.get("/layers")
async def list_layers(admin=Depends(require_super_admin)):
    async with _db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, order_idx, default_on, modes, status, updated_at, updated_by "
            "FROM layer_config ORDER BY order_idx"
        )
        sync_rows = await conn.fetch("SELECT source, last_synced_at FROM sync_log")
    last_by_source = {r["source"]: r["last_synced_at"] for r in sync_rows}
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        ops = layer_ops.resolve_ops(r["id"])
        rows_count = None
        age = None
        if ops:
            last = last_by_source.get(ops["log_source"]) if ops["log_source"] else None
            if last:
                age = (now - last).total_seconds()
            if ops["count_sql"]:
                try:
                    async with _db.pool.acquire() as c2:
                        # Timeout guard: some tables (e.g. partitioned ais_positions)
                        # can hold tens of millions of rows — an exact count(*) must
                        # never be allowed to block the whole endpoint. asyncpg raises
                        # a plain TimeoutError on expiry, which the except below catches.
                        rows_count = await c2.fetchval(ops["count_sql"], timeout=2.0)
                except Exception:  # noqa: BLE001 — a bad/slow table shouldn't break the list
                    rows_count = None
        out.append({
            "id": r["id"], "order_idx": r["order_idx"], "default_on": r["default_on"],
            "modes": list(r["modes"]), "status": r["status"],
            "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            "updated_by": r["updated_by"],
            "health": {
                "has_table": bool(ops and ops["tables"]),
                "rows": rows_count,
                **layer_ops.age_bucket(age),
            },
        })
    return out


@router.post("/layers/{layer_id}/status")
async def set_status(layer_id: str, body: _StatusBody,
                     admin=Depends(require_super_admin)):
    try:
        audit.validate_status(body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    ops = layer_ops.resolve_ops(layer_id)
    async with _db.pool.acquire() as conn:
        old = await conn.fetchval("SELECT status FROM layer_config WHERE id=$1", layer_id)
        if old is None:
            raise HTTPException(404, f"unknown layer {layer_id!r}")
        async with conn.transaction():
            await conn.execute(
                "UPDATE layer_config SET status=$2, updated_at=now(), updated_by=$3 WHERE id=$1",
                layer_id, body.status, admin["username"],
            )
            sync_act = audit.sync_action_for_status(old, body.status,
                                                    ops["sync_source"] if ops else None)
            if sync_act == "pause":
                await conn.execute(
                    "INSERT INTO paused_syncs (action) VALUES ($1) ON CONFLICT DO NOTHING",
                    ops["sync_source"])
            elif sync_act == "unpause":
                await conn.execute("DELETE FROM paused_syncs WHERE action=$1", ops["sync_source"])
            await audit.write_audit(conn, admin["username"], "status", layer_id,
                                    {"from": old, "to": body.status, "sync": sync_act})
    if sync_act in ("pause", "unpause"):
        invalidate_paused_cache()
    _bust_layer_cache()
    return {"ok": True, "id": layer_id, "status": body.status, "sync": sync_act}


@router.post("/layers/{layer_id}/purge")
async def purge_layer(layer_id: str, admin=Depends(require_super_admin)):
    async with _db.pool.acquire() as conn:
        status = await conn.fetchval("SELECT status FROM layer_config WHERE id=$1", layer_id)
        if status is None:
            raise HTTPException(404, f"unknown layer {layer_id!r}")
        ok, reason = audit.purge_allowed(layer_id, status)
        if not ok:
            raise HTTPException(409, reason)
        ops = layer_ops.resolve_ops(layer_id)
        before = {}
        async with conn.transaction():
            for tbl in ops["tables"]:
                before[tbl] = await conn.fetchval(f"SELECT count(*) FROM {tbl}")
                await conn.execute(f"TRUNCATE TABLE {tbl}")
            await audit.write_audit(conn, admin["username"], "purge", layer_id,
                                    {"tables": list(ops["tables"]), "rows_before": before})
    return {"ok": True, "id": layer_id, "purged": before}


@router.patch("/layers/{layer_id}")
async def patch_layer(layer_id: str, body: _PatchBody, admin=Depends(require_super_admin)):
    async with _db.pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM layer_config WHERE id=$1", layer_id)
        if not exists:
            raise HTTPException(404, f"unknown layer {layer_id!r}")
        async with conn.transaction():
            await conn.execute(
                """UPDATE layer_config
                      SET order_idx  = COALESCE($2, order_idx),
                          default_on = COALESCE($3, default_on),
                          modes      = COALESCE($4::text[], modes),
                          updated_at = now(), updated_by = $5
                    WHERE id = $1""",
                layer_id, body.order_idx, body.default_on, body.modes, admin["username"],
            )
            await audit.write_audit(conn, admin["username"], "patch", layer_id,
                                    body.model_dump(exclude_none=True))
    _bust_layer_cache()
    return {"ok": True, "id": layer_id}


# ── Operations wrappers (cookie-authed mirrors of main.py's token-authed /admin/sync/*) ──
# The existing token-authed endpoints in main.py (used by the Mac self-healing monitor)
# are untouched; these are additive cookie-authed wrappers for the admin panel.

@router.get("/audit")
async def list_audit(limit: int = 100, admin=Depends(require_super_admin)):
    async with _db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, ts, actor, action, target, detail FROM admin_audit "
            "ORDER BY ts DESC LIMIT $1",
            limit,
        )
    return [
        {
            "id": r["id"],
            "ts": r["ts"].isoformat() if r["ts"] else None,
            "actor": r["actor"],
            "action": r["action"],
            "target": r["target"],
            "detail": json.loads(r["detail"]) if isinstance(r["detail"], str) else r["detail"],
        }
        for r in rows
    ]


@router.get("/ops/sources")
async def ops_sources(admin=Depends(require_super_admin)):
    import main
    async with _db.pool.acquire() as conn:
        sync_rows = await conn.fetch(
            "SELECT source, last_synced_at, records_added, total_records FROM sync_log ORDER BY source")
        paused_rows = await conn.fetch("SELECT action FROM paused_syncs")
    paused = {r["action"] for r in paused_rows}
    synced = {
        r["source"]: {
            "source": r["source"],
            "sync_action": main._SOURCE_TO_ACTION.get(r["source"]),
            "last_synced_at": r["last_synced_at"].isoformat() if r["last_synced_at"] else None,
            "records_added": r["records_added"], "total_records": r["total_records"],
        } for r in sync_rows
    }
    for action_key in main._SYNC_SOURCES:
        db_key = next((k for k, v in main._SOURCE_TO_ACTION.items() if v == action_key), None)
        if db_key and db_key not in synced:
            synced[db_key] = {"source": db_key, "sync_action": action_key,
                              "last_synced_at": None, "records_added": None, "total_records": None}
    return {"paused": list(paused),
            "sources": sorted(synced.values(), key=lambda x: x["source"])}


@router.post("/ops/sync/{source}")
async def ops_sync(source: str, admin=Depends(require_super_admin)):
    import main
    fn = main._SYNC_SOURCES.get(source)
    if not fn:
        raise HTTPException(404, f"unknown source {source!r}")
    if await is_sync_paused(source):
        raise HTTPException(409, f"sync {source!r} is paused; unpause first")
    import asyncio
    asyncio.create_task(main._run_tracked(source, fn()))
    async with _db.pool.acquire() as conn:
        await audit.write_audit(conn, admin["username"], "force_sync", source, None)
    return {"status": "started", "source": source}


@router.post("/ops/pause/{source}")
async def ops_pause(source: str, admin=Depends(require_super_admin)):
    async with _db.pool.acquire() as conn:
        await conn.execute("INSERT INTO paused_syncs (action) VALUES ($1) ON CONFLICT DO NOTHING", source)
        await audit.write_audit(conn, admin["username"], "pause", source, None)
    invalidate_paused_cache()
    return {"status": "paused", "source": source}


@router.post("/ops/unpause/{source}")
async def ops_unpause(source: str, admin=Depends(require_super_admin)):
    async with _db.pool.acquire() as conn:
        await conn.execute("DELETE FROM paused_syncs WHERE action=$1", source)
        await audit.write_audit(conn, admin["username"], "unpause", source, None)
    invalidate_paused_cache()
    return {"status": "unpaused", "source": source}


@router.post("/ops/cache/clear")
async def ops_cache_clear(admin=Depends(require_super_admin)):
    import main
    from domains import CACHE_CLEARING_DOMAINS

    # Mirrors main.admin_cache_clear. Domain-owned caches are swept through
    # CACHE_CLEARING_DOMAINS rather than named here — a second hand-maintained
    # copy of that list is what broke this endpoint after the Phase 3 split.
    main._cache.clear()
    for _domain in CACHE_CLEARING_DOMAINS:
        _domain.clear_caches()
    async with _db.pool.acquire() as conn:
        await audit.write_audit(conn, admin["username"], "cache_clear", None, None)
    return {"status": "cleared"}


# ── Settings: admin token rotation ──

import os as _os
import secrets as _secrets
from pathlib import Path as _Path


def _rewrite_env_var(key: str, value: str, env_path=None) -> None:
    """Idempotently set KEY=value in backend/.env (file lives beside main.py).

    Writes atomically (tmp file + os.replace) and owner-only (0o600) so a
    crash mid-write can't corrupt the credentials file and the file's mode
    can't leak beyond the owning user. `env_path` is injectable for tests;
    `main` is only imported when it's not supplied.
    """
    if env_path is None:
        import main
        env_path = _Path(main.__file__).resolve().parent / ".env"
    env_path = _Path(env_path)
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    out, found = [], False
    for ln in lines:
        if ln.startswith(f"{key}="):
            out.append(f"{key}={value}"); found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"{key}={value}")
    data = "\n".join(out) + "\n"
    tmp = env_path.with_name(env_path.name + ".tmp")
    fd = _os.open(str(tmp), _os.O_WRONLY | _os.O_CREAT | _os.O_TRUNC, 0o600)
    try:
        with _os.fdopen(fd, "w") as f:
            f.write(data)
    except Exception:
        try: _os.unlink(tmp)
        except OSError: pass
        raise
    _os.chmod(tmp, 0o600)
    _os.replace(tmp, env_path)  # atomic rename


@router.post("/settings/rotate-token")
async def rotate_token(admin=Depends(require_super_admin)):
    import auth
    new = "abyssal-admin-" + _secrets.token_urlsafe(18)
    _rewrite_env_var("ADMIN_DASHBOARD_TOKEN", new)
    auth.ADMIN_DASHBOARD_TOKEN = new  # hot-reload the in-memory value (auth.py owns this — see its module docstring)
    _os.environ["ADMIN_DASHBOARD_TOKEN"] = new
    async with _db.pool.acquire() as conn:
        await audit.write_audit(conn, admin["username"], "rotate_token", None, None)  # never store the token
    return {
        "token": new,
        "warning": ("The Mac self-healing monitor stores this token. Update it in the "
                    "monitor config (layer-sync-monitor-thresholds/notify env) or its "
                    "force-syncs will 403 until you do."),
    }
