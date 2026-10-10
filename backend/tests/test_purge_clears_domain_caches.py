# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""A purge empties the table; the API's cached documents built from it must go too (the argo-oxygen map documents
are keyed on a `loaded_at` the purge does not touch, so they would be served until the next restart)."""
import pytest

import audit
import db
from domains import argo_oxygen_points as dom
from routers import admin_layers_api as api


class _Conn:
    def __init__(self):
        self.sql: list[str] = []

    async def fetchval(self, sql, *a):
        self.sql.append(sql)
        return "disabled" if "layer_config" in sql else 7

    async def execute(self, sql, *a):
        self.sql.append(sql)

    def transaction(self):
        return _Tx()


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Acq:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _Acq()


@pytest.mark.asyncio
async def test_purging_a_layer_drops_the_cached_documents_built_from_it(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr(db, "pool", _Pool(conn))

    async def no_audit(*a, **k):
        return None
    monkeypatch.setattr(audit, "write_audit", no_audit)
    dom._doc_cache[("points", 500)] = ("stamp", b"cached pre-purge document")
    out = await api.purge_layer("argo-oxygen-points", admin={"username": "t"})
    assert out["purged"] == {"argo_doxy_profiles": 7}
    assert any("TRUNCATE TABLE argo_doxy_profiles" in q for q in conn.sql)
    assert dom._doc_cache == {}
