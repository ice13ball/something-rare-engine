# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Maintenance privileges and isolated token persistence; no real DB/jobs."""
import asyncio
import stat
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

import auth
import db
import main
from domains import biodiversity
from routers import reports, admin_layers_api


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/v1/admin/rebuild-hotspot-grid",
    "/v1/admin/backfill-iucn",
    "/v1/reports/refresh-species-cache",
])
async def test_maintenance_requires_admin_even_with_bff_key(monkeypatch, path):
    monkeypatch.setattr(auth, "ADMIN_DASHBOARD_TOKEN", "synthetic-admin-token")
    monkeypatch.setenv("ABYSSAL_API_KEY", "synthetic-bff-key")
    jobs = []
    for module, name in [(biodiversity, "rebuild_hotspot_grid"),
                         (biodiversity, "backfill_iucn_categories"),
                         (reports, "refresh_species_cache")]:
        job = AsyncMock()
        monkeypatch.setattr(module, name, job)
        jobs.append(job)
    monkeypatch.setattr(db, "pool", object())
    monkeypatch.setattr(reports, "ensure_species_cache_table", AsyncMock())
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as c:
        for headers in [{}, {"X-API-Key": "synthetic-bff-key"},
                        {"X-Admin-Token": "wrong"}]:
            assert (await c.post(path, headers=headers)).status_code == 403
        assert sum(j.call_count for j in jobs) == 0
        assert (await c.post(path, headers={"X-Admin-Token": "synthetic-admin-token"})).status_code == 200
        await asyncio.sleep(0)
    assert sum(j.await_count for j in jobs) == 1


def test_token_rotation_persists_outside_env(monkeypatch, tmp_path):
    token = tmp_path / "admin-token"
    token.write_text("old")
    monkeypatch.setenv("ADMIN_DASHBOARD_TOKEN_FILE", str(token))
    monkeypatch.setenv("ADMIN_DASHBOARD_TOKEN", "old-env-value")
    def forbid_env_write(*args, **kwargs):
        pytest.fail("isolated service must never write deploy .env")
    monkeypatch.setattr(admin_layers_api, "_rewrite_env_var", forbid_env_write)
    admin_layers_api._persist_admin_token("new-token")
    assert auth.load_admin_token() == "new-token"
    assert stat.S_IMODE(token.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [token]


def test_missing_configured_token_file_does_not_fall_back(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_DASHBOARD_TOKEN_FILE", str(tmp_path / "missing"))
    monkeypatch.setenv("ADMIN_DASHBOARD_TOKEN", "old-token")
    with pytest.raises(FileNotFoundError):
        auth.load_admin_token()
