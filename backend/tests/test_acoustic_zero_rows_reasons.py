# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

""""0 rows returned" must not mean one thing for four different reasons.

Measured on production 2026-09-18: `swfsc`, `afsc`, `rutgers_njrmi` and
`md_wea_cpod` all hit the same `if not rows:` branch in
`_sync_acoustic_stations` every run, for three DIFFERENT causes — no metadata
published, every deployment on a mobile platform, and the one deployment
published at (0, 0) — and the line could not tell them apart. Nothing reached
`sync_log`, so the staleness monitor saw four silent zeros where it should
have seen three distinguishable, checkable reasons.

This file guards two layers of that fix:

1. `ingestion/acoustic_noaa_archive_ingest.py::fetch_program_stations` builds
   its reason from counters THIS RUN incremented, never a per-program
   hardcoded string — so the causes below are produced by stubbing the walk,
   not by asserting a literal that happens to match a comment.
2. `domains/acoustic.py::sync_acoustic_stations` reads that reason via
   `getattr(rows, "note", None)` and, when present, records it through
   `sync_log.log_sync_skipped` — never through `log_sync`, which would stamp
   `last_synced_at = NOW()` and make an unfetchable program look freshly
   synced forever.
"""
import logging

import pytest

from ingestion import acoustic_noaa_archive_ingest as mod
from ingestion.acoustic_noaa_archive_ingest import _StationRows

# ─────────────────────────────────────────────────────────────────────────────
# Test doubles for the GCS walk — no network, no real bucket.
# ─────────────────────────────────────────────────────────────────────────────


def _install_walk(monkeypatch, paths: list[str], per_path: dict[str, dict]):
    """Stub `_discover_metadata_jsons` to return `paths` and `_fetch_json` to
    serve `per_path[path]` (or None if a path isn't listed)."""

    async def _discover(client, prefix, max_depth=6):
        return list(paths)

    async def _fetch(client, path):
        return per_path.get(path)

    monkeypatch.setattr(mod, "_discover_metadata_jsons", _discover)
    monkeypatch.setattr(mod, "_fetch_json", _fetch)


def _meta_mobile(platform="glider", site="S1"):
    return {
        "SITE": site,
        "PLATFORM_NAME": platform,
        "DEPLOYMENT": {
            "DEPLOYMENT_TIME": "2020-01-01T00:00:00",
            "DEPLOY_LAT": "10.0",
            "DEPLOY_LON": "-70.0",
        },
    }


def _meta_null_island(site="WEA"):
    return {
        "SITE": site,
        "PLATFORM_NAME": "Mooring",
        "DEPLOYMENT": {
            "DEPLOYMENT_TIME": "2019-06-01T00:00:00",
            "DEPLOY_LAT": "0",
            "DEPLOY_LON": "0",
        },
    }


def _meta_ok(site="S1", lat="10.0", lon="-70.0"):
    return {
        "SITE": site,
        "PLATFORM_NAME": "Mooring",
        "DEPLOYMENT": {
            "DEPLOYMENT_TIME": "2020-01-01T00:00:00",
            "DEPLOY_LAT": lat,
            "DEPLOY_LON": lon,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Each of the three causes gets its own reason text.
# ─────────────────────────────────────────────────────────────────────────────


async def test_no_metadata_under_the_prefix_names_the_prefix_and_the_zero(monkeypatch):
    """`swfsc` — measured 2026-09-18: no metadata JSON at all under its prefix."""
    _install_walk(monkeypatch, paths=[], per_path={})

    rows = await mod.fetch_program_stations("swfsc")

    assert rows == []
    note = getattr(rows, "note", None)
    assert note == "no metadata published under swfsc/audio/ (0 files)", note


async def test_a_single_mobile_deployment_says_all_mobile_by_rule(monkeypatch):
    """`afsc` — measured 2026-09-18: 1 deployment, a glider, dropped by the
    existing mobile-platform rule."""
    path = "afsc/audio/x/metadata/y.json"
    _install_walk(monkeypatch, paths=[path], per_path={path: _meta_mobile()})

    rows = await mod.fetch_program_stations("afsc")

    assert rows == []
    note = getattr(rows, "note", None)
    assert note == "1 deployment, all on mobile platforms (skipped by rule)", note


async def test_rutgers_njrmi_glider_produces_the_same_shape_of_reason(monkeypatch):
    """`rutgers_njrmi` — measured 2026-09-18: 1 deployment, glider ru40, same
    mobile-platform rule as afsc. Same cause must produce the same sentence
    shape, not a per-program string."""
    path = "rutgers_njrmi/audio/x/metadata/y.json"
    _install_walk(monkeypatch, paths=[path],
                   per_path={path: _meta_mobile(platform="glider", site="ru40")})

    rows = await mod.fetch_program_stations("rutgers_njrmi")

    assert rows == []
    note = getattr(rows, "note", None)
    assert note == "1 deployment, all on mobile platforms (skipped by rule)", note


async def test_a_single_null_island_deployment_names_the_position(monkeypatch):
    """`md_wea_cpod` — measured 2026-09-18: 1 moored deployment whose
    published position is (0, 0), dropped by the existing Null Island guard."""
    path = "MD_WEA_CPOD/metadata/z.json"
    _install_walk(monkeypatch, paths=[path], per_path={path: _meta_null_island()})

    rows = await mod.fetch_program_stations("md_wea_cpod")

    assert rows == []
    note = getattr(rows, "note", None)
    assert note == "1 deployment, position (0,0) published upstream", note


async def test_a_combined_cause_names_both_when_both_apply(monkeypatch):
    """More than one cause in the same run must not collapse to one clause —
    or silently pick one and drop the other."""
    p1, p2 = "pifsc/audio/a/metadata/1.json", "pifsc/audio/b/metadata/2.json"
    _install_walk(monkeypatch, paths=[p1, p2], per_path={
        p1: _meta_mobile(site="A"),
        p2: _meta_null_island(site="B"),
    })

    rows = await mod.fetch_program_stations("pifsc")

    assert rows == []
    note = getattr(rows, "note", None)
    assert note == (
        "2 deployments, 1 on mobile platforms (skipped by rule) and "
        "1 at position (0,0) published upstream"
    ), note


# ─────────────────────────────────────────────────────────────────────────────
# Positive control — a program that yields stations reports no reason.
# ─────────────────────────────────────────────────────────────────────────────


async def test_a_program_with_stations_reports_no_reason(monkeypatch):
    path = "pifsc/audio/a/metadata/1.json"
    _install_walk(monkeypatch, paths=[path], per_path={path: _meta_ok()})

    rows = await mod.fetch_program_stations("pifsc")

    assert len(rows) == 1
    assert getattr(rows, "note", None) is None, (
        "a program that DID yield stations attached a reason anyway")


def test_a_nonempty_stationrows_still_compares_equal_to_a_plain_list():
    """⛔ Guard the wrapper itself: if `_StationRows.__eq__` ever stopped
    delegating to `list`, every `rows == []` assertion above would start
    failing for the wrong reason."""
    assert _StationRows([], "irrelevant") == []
    assert _StationRows([{"a": 1}], None) == [{"a": 1}]


# ─────────────────────────────────────────────────────────────────────────────
# The domain: reads the reason via getattr, records it via log_sync_skipped —
# never log_sync — and a plain list from another fetcher must not crash it.
# ─────────────────────────────────────────────────────────────────────────────

from domains import acoustic  # noqa: E402  (after the ingestion-module tests above)


class _FakeConn:
    async def fetchval(self, *a, **kw):
        return 0

    async def execute(self, *a, **kw):
        return None


class _FakeAcquire:
    async def __aenter__(self):
        return _FakeConn()

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def acquire(self):
        return _FakeAcquire()


class _Recorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, *args, **kwargs):
        self.calls.append(args)


@pytest.fixture
def _stub_db(monkeypatch):
    import db
    monkeypatch.setattr(db, "pool", _FakePool())


async def test_domain_records_the_reason_through_log_sync_skipped(monkeypatch, _stub_db):
    async def _fake_fetch():
        return _StationRows([], "no metadata published under fake/prefix/ (0 files)")

    monkeypatch.setattr(acoustic, "station_sources", lambda: [("fakeprog", _fake_fetch)])
    skipped = _Recorder()
    logged = _Recorder()
    monkeypatch.setattr(acoustic, "_log_sync_skipped", skipped)
    monkeypatch.setattr(acoustic, "_log_sync", logged)

    await acoustic.sync_acoustic_stations(force=True)

    assert skipped.calls == [
        ("acoustic-fakeprog", "no metadata published under fake/prefix/ (0 files)")
    ], skipped.calls
    # The aggregate end-of-run call is the ONLY log_sync call, and it names the
    # aggregate source — never the per-program one that was skipped.
    assert logged.calls == [("acoustic-stations", 0, 0)], logged.calls


async def test_a_plain_list_from_another_fetcher_does_not_crash_and_logs_no_reason(
    monkeypatch, _stub_db, caplog,
):
    async def _fake_fetch():
        return []  # a bare list — 23 of the 24 fetchers behave exactly like this

    monkeypatch.setattr(acoustic, "station_sources", lambda: [("ooi", _fake_fetch)])
    skipped = _Recorder()
    logged = _Recorder()
    monkeypatch.setattr(acoustic, "_log_sync_skipped", skipped)
    monkeypatch.setattr(acoustic, "_log_sync", logged)

    with caplog.at_level(logging.INFO):
        await acoustic.sync_acoustic_stations(force=True)

    assert skipped.calls == [], "a plain list has no reason and must not skip-log one"
    assert any("no reason reported" in r.getMessage() for r in caplog.records), (
        "a plain empty list must say plainly that nothing was reported, not "
        "invent a reason or say nothing at all")
