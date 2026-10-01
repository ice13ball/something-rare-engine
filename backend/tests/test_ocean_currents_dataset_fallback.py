# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""fetch_currents falls back reanalysis -> NRT only on a time-range error."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pytest

from services import ocean_currents as oc

RANGE_MSG = (
    "Some of your subset selection [2026-08-06 11:49:25+00:00, 2026-08-13 11:49:25+00:00] "
    "for the time dimension exceed the dataset coordinates "
    "[1993-01-01 00:00:00+00:00, 2026-06-23 00:00:00+00:00]"
)
SENTINEL = object()


class FakeCM:
    def __init__(self, reanalysis_error=RANGE_MSG, nrt_error=None):
        self.reanalysis_error = reanalysis_error
        self.nrt_error = nrt_error
        self.calls = []

    def open_dataset(self, dataset_id, **kwargs):
        self.calls.append(dataset_id)
        err = self.reanalysis_error if dataset_id == oc.DATASET_REANALYSIS else self.nrt_error
        if err:
            raise Exception(err)
        return SENTINEL


@pytest.fixture
def make_fake(monkeypatch):
    def _make(**kw):
        fake = FakeCM(**kw)
        monkeypatch.setattr(oc, "_cm", lambda: fake)
        monkeypatch.setattr(oc, "_credentials", lambda: {"username": "u", "password": "p"})
        return fake
    return _make


def _ago(days):
    return datetime.now(timezone.utc) - timedelta(days=days)


def test_old_profile_past_reanalysis_end_falls_back_to_nrt(make_fake):
    fake = make_fake()
    ds, used = oc.fetch_currents(0.0, 0.0, _ago(50), 1000, 168)
    assert ds is SENTINEL
    assert used == oc.DATASET_NRT
    assert fake.calls == [oc.DATASET_REANALYSIS, oc.DATASET_NRT]


def test_fallback_is_logged_once_without_credentials(make_fake, caplog):
    make_fake()
    with caplog.at_level(logging.INFO, logger=oc.__name__):
        oc.fetch_currents(0.0, 0.0, _ago(50), 1000, 168)
    msgs = [r.getMessage() for r in caplog.records if "retrying with NRT" in r.getMessage()]
    assert len(msgs) == 1
    assert "password" not in msgs[0].lower()


def test_auth_error_does_not_fall_back(make_fake):
    fake = make_fake(reanalysis_error="401 Unauthorized")
    with pytest.raises(oc.CMEMSUnavailableError):
        oc.fetch_currents(0.0, 0.0, _ago(50), 1000, 168)
    assert fake.calls == [oc.DATASET_REANALYSIS]


def test_nrt_failure_after_fallback_raises(make_fake):
    fake = make_fake(nrt_error="503 upstream down")
    with pytest.raises(oc.CMEMSUnavailableError):
        oc.fetch_currents(0.0, 0.0, _ago(50), 1000, 168)
    assert fake.calls == [oc.DATASET_REANALYSIS, oc.DATASET_NRT]


def test_recent_profile_goes_straight_to_nrt(make_fake):
    fake = make_fake()
    ds, used = oc.fetch_currents(0.0, 0.0, _ago(5), 1000, 168)
    assert used == oc.DATASET_NRT
    assert fake.calls == [oc.DATASET_NRT]


def test_dataset_label_maps_ids_to_stored_vocabulary():
    assert oc.dataset_label(oc.DATASET_NRT) == "nrt"
    assert oc.dataset_label(oc.DATASET_REANALYSIS) == "reanalysis"


def test_plume_history_stores_dataset_actually_used(monkeypatch):
    from services import plume_history as ph

    when = _ago(50)

    class FakePool:
        def __init__(self):
            self.inserts = []

        async def fetch(self, *a, **k):
            return [{"profile_id": "p1", "platform_id": "x", "profile_date": when,
                     "lon": 1.0, "lat": 2.0}]

        async def fetchrow(self, *a, **k):
            return None

        async def fetchval(self, *a, **k):
            return None

        async def execute(self, sql, *args):
            if "INSERT INTO plume_paths" in sql:
                self.inserts.append(args)

    result = oc.BacktrackResult(path=[(1.0, 2.0), (0.9, 2.0)], origin=(0.9, 2.0), u_mean=0.0,
                                v_mean=0.0, speed_cms=1.0, steps_completed=2,
                                dataset_id=oc.DATASET_NRT)
    monkeypatch.setattr(ph, "backtrack", lambda **kw: result)

    async def _no_contractor(*a, **k):
        return None

    monkeypatch.setattr(ph, "_resolve_contractor", _no_contractor)

    async def _no_sleep(*a, **k):
        return None

    monkeypatch.setattr(ph.asyncio, "sleep", _no_sleep)
    pool = FakePool()
    assert asyncio.run(ph.compute_pending_plume_paths(pool)) == 1
    assert pool.inserts and pool.inserts[0][8] == "nrt"
