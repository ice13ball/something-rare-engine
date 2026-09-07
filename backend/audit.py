# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Pure layer-status transition rules + the admin_audit DB writer."""
from __future__ import annotations
import json
from layer_ops import has_table

VALID_STATUSES = ("enabled", "disabled", "retired")


def validate_status(s: str) -> None:
    if s not in VALID_STATUSES:
        raise ValueError(f"invalid status {s!r}; must be one of {VALID_STATUSES}")


def purge_allowed(layer_id: str, status: str) -> tuple[bool, str]:
    if status == "enabled":
        return False, "Layer is enabled; disable or retire it before purging."
    if not has_table(layer_id):
        return False, "Layer has no data table (baked field/raster); nothing to purge."
    return True, ""


def sync_action_for_status(old: str, new: str, sync_source: str | None) -> str | None:
    """Retiring pauses the layer's scheduled sync; un-retiring unpauses it."""
    if sync_source is None:
        return None
    if new == "retired" and old != "retired":
        return "pause"
    if old == "retired" and new != "retired":
        return "unpause"
    return None


async def write_audit(conn, actor: str, action: str,
                      target: str | None = None, detail: dict | None = None) -> None:
    """Best-effort audit row. Never raises — an audit failure must not 500 the action."""
    try:
        await conn.execute(
            "INSERT INTO admin_audit (actor, action, target, detail) VALUES ($1,$2,$3,$4)",
            actor, action, target,
            json.dumps(detail) if detail is not None else None,
        )
    except Exception:  # noqa: BLE001 — audit is advisory, never blocks the action
        import logging
        logging.getLogger("abyssal").warning("admin_audit write failed for %s/%s", action, target)
