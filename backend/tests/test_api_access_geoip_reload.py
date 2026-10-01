# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""GeoIP hot-reload: executes the real reload path with fake readers and a fake clock.
No .mmdb file is used or committed (MaxMind EULA); files here are empty placeholders."""

import os

import pytest

from api_access import geoip as gm


class _Reader:
    def __init__(self, path, iso="US"):
        self.path, self.iso = path, iso

    def country(self, ip):
        return type("R", (), {"country": type("C", (), {"iso_code": self.iso})()})()


class _Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t


def _replace(path, data=b"x"):
    """What geoipupdate does: write a temp file, rename over the target (new inode)."""
    tmp = str(path) + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


@pytest.fixture
def env(tmp_path, monkeypatch):
    opened = []

    def fake_open(path):
        if os.path.getsize(path) == 0:
            raise ValueError("corrupt")
        r = _Reader(path, iso="X" + str(len(opened)))
        opened.append(r)
        return r

    monkeypatch.setattr(gm, "_open_reader", fake_open)
    monkeypatch.setattr(gm, "_current", None)
    cdb = tmp_path / "country.mmdb"
    cdb.write_bytes(b"v1")
    monkeypatch.setenv("GEOIP_COUNTRY_DB", str(cdb))
    monkeypatch.delenv("GEOIP_ASN_DB", raising=False)
    clock = _Clock()
    g = gm.load_geoip()
    g._clock = clock
    g._next_check = clock() + g._interval
    return g, cdb, clock, opened


def test_reload_after_inode_change_and_interval(env):
    g, cdb, clock, opened = env
    assert g.lookup("8.8.8.8")[0] == "X0"
    _replace(cdb, b"v2")
    clock.t += gm.RELOAD_CHECK_INTERVAL_S + 1
    assert g.lookup("8.8.8.8")[0] == "X1"
    assert len(opened) == 2


def test_no_reload_before_interval(env):
    g, cdb, clock, opened = env
    _replace(cdb, b"v2")
    clock.t += gm.RELOAD_CHECK_INTERVAL_S - 5
    assert g.lookup("8.8.8.8")[0] == "X0"
    assert len(opened) == 1


def test_unchanged_file_is_not_reopened(env):
    g, cdb, clock, opened = env
    clock.t += gm.RELOAD_CHECK_INTERVAL_S + 1
    g.lookup("8.8.8.8")
    assert len(opened) == 1


def test_stat_is_rate_limited(env, monkeypatch):
    g, cdb, clock, opened = env
    calls = []
    real = gm._signature
    monkeypatch.setattr(gm, "_signature", lambda p: (calls.append(p), real(p))[1])
    for _ in range(50):
        g.lookup("8.8.8.8")
    assert calls == []
    clock.t += gm.RELOAD_CHECK_INTERVAL_S + 1
    for _ in range(50):
        g.lookup("8.8.8.8")
    assert len(calls) == 1


def test_file_vanishes_keeps_old_reader_and_never_raises(env):
    g, cdb, clock, opened = env
    os.remove(cdb)
    clock.t += gm.RELOAD_CHECK_INTERVAL_S + 1
    assert g.lookup("8.8.8.8")[0] == "X0"
    assert g.status()["country"] is True


def test_corrupt_new_file_keeps_old_reader(env, caplog):
    g, cdb, clock, opened = env
    _replace(cdb, b"")  # empty -> fake_open raises
    for _ in range(3):
        clock.t += gm.RELOAD_CHECK_INTERVAL_S + 1
        assert g.lookup("8.8.8.8")[0] == "X0"
    assert sum("reload failed" in r.message for r in caplog.records) == 1  # logged once


def test_file_appearing_later_is_picked_up(tmp_path, monkeypatch):
    monkeypatch.setattr(gm, "_open_reader", lambda p: _Reader(p, "PL"))
    monkeypatch.setattr(gm, "_current", None)
    cdb = tmp_path / "late.mmdb"
    monkeypatch.setenv("GEOIP_COUNTRY_DB", str(cdb))
    monkeypatch.delenv("GEOIP_ASN_DB", raising=False)
    g = gm.load_geoip()
    clock = _Clock()
    g._clock, g._next_check = clock, clock() + g._interval
    assert g.lookup("8.8.8.8") == (None, None)
    assert gm.geoip_status()["country"] is False
    cdb.write_bytes(b"v1")
    clock.t += gm.RELOAD_CHECK_INTERVAL_S + 1
    assert g.lookup("8.8.8.8")[0] == "PL"
    assert gm.geoip_status()["country"] is True


def test_lookup_never_raises_if_reload_machinery_breaks(env, monkeypatch):
    g, cdb, clock, opened = env
    monkeypatch.setattr(gm, "_signature", lambda p: 1 / 0)
    clock.t += gm.RELOAD_CHECK_INTERVAL_S + 1
    assert g.lookup("8.8.8.8")[0] == "X0"
    g._clock = lambda: 1 / 0
    assert g.lookup("8.8.8.8")[0] == "X0"


def test_status_shape_on_and_off(env, monkeypatch):
    g, cdb, clock, opened = env
    s = gm.geoip_status()
    assert s["country"] is True and s["asn"] is False
    assert s["asn_db_mtime"] is None and s["country_db_mtime"].endswith("+00:00")
    monkeypatch.setattr(gm, "_current", None)
    assert gm.geoip_status() == {"country": False, "asn": False,
                                 "country_db_mtime": None, "asn_db_mtime": None}


@pytest.mark.asyncio
async def test_overview_includes_geoip_and_keeps_existing_fields(env, monkeypatch):
    from routers import admin_api

    class _Conn:
        async def fetchval(self, q): return 7

    class _Acq:
        async def __aenter__(self): return _Conn()
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(admin_api._db, "pool", type("P", (), {"acquire": lambda self: _Acq()})(), raising=False)
    out = await admin_api.overview(_=None)
    assert {"orgs", "active_keys", "requests_24h"} <= set(out)
    assert out["geoip"]["country"] is True and out["geoip"]["asn"] is False
    monkeypatch.setattr(gm, "_current", None)
    assert (await admin_api.overview(_=None))["geoip"]["country"] is False
