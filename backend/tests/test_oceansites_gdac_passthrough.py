# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Measured values must pass through _fetch_station unchanged.

Measured on 2026-09-23 for station 10N110W (GDAC OPeNDAP): SST 29.5703,
AIRT 29.5481, PSAL 32.9914, WSPD 5.49152, WDIR 98.59. The source line rounded
these before storage in oceansites_stations.latest_obs, in violation of
docs/methods/data-passthrough.md ("measured values pass through exactly as
the source published them; formatting belongs in the display layer").

This does NOT touch pmel_erddap.py: its wind speed/direction are OUR
derivation from u/v components, a different question.
"""
import pytest

import ingestion.oceansites_gdac as gdac

_TS = "2026-09-23T00:00:00Z"

# station_name -> fake latest-file map (var_suffix -> filename)
_FAKE_LATEST = {
    "SST": "OS_10N110W_2026_R_SST_10min.nc",
    "AIRT": "OS_10N110W_2026_R_AIRT_10min.nc",
    "BARO": "OS_10N110W_2026_R_BARO_10min.nc",
    "SALT": "OS_10N110W_2026_R_SALT_10min.nc",
    "WIND": "OS_10N110W_2026_R_WIND_10min.nc",
}

# (file_var_suffix, internal_var) -> measured (value, ts), exactly as the
# source (GDAC OPeNDAP) published them — no rounding.
_MEASURED = {
    ("SST", "SST"): (29.5703, _TS),
    ("AIRT", "AIRT"): (29.5481, _TS),
    ("BARO", "ATMS"): (1008.57, _TS),
    ("SALT", "PSAL"): (32.9914, _TS),
    ("WIND", "WSPD"): (5.49152, _TS),
    ("WIND", "WDIR"): (98.59, _TS),
}


@pytest.mark.asyncio
async def test_fetch_station_stores_measured_values_unrounded(monkeypatch):
    async def fake_fetch_catalog(client, dirname):
        return ["dummy.nc"]  # non-empty so _fetch_station proceeds

    def fake_pick_latest_files(filenames):
        return dict(_FAKE_LATEST)

    async def fake_fetch_last_value(client, url, var):
        # url encodes the file suffix via its filename; recover (suffix, var)
        for suffix, fn in _FAKE_LATEST.items():
            if fn in url:
                return _MEASURED[(suffix, var)]
        raise AssertionError(f"unexpected fetch: {url} {var}")

    monkeypatch.setattr(gdac, "_fetch_catalog", fake_fetch_catalog)
    monkeypatch.setattr(gdac, "_pick_latest_files", fake_pick_latest_files)
    monkeypatch.setattr(gdac, "_fetch_last_value", fake_fetch_last_value)

    import httpx

    async with httpx.AsyncClient() as client:
        result = await gdac._fetch_station(client, "10N110W")

    assert result is not None
    station_name, obs = result
    assert station_name == "10N110W"
    assert obs == {
        "wtmp": 29.5703,
        "atmp": 29.5481,
        "pres": 1008.57,
        "sss": 32.9914,
        "wspd": 5.49152,
        "wdir": 98.59,
        "obs_time": _TS,
    }
