# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Which source feeds which OceanSITES mooring.

Measured on production 2026-10-01: 54 of 1,038 moorings carried a reading, and
three of the reasons were ours, not the sources':

1. NDBC was asked for the OceanOPS reference ("1500009"); NDBC knows the buoy
   as WMO 15009. Every request 404'd — NDBC fed 0 moorings while it had
   same-day readings for 9 of them.
2. PMEL was matched by name only. OceanOPS "00N03" is PMEL "0n3w";
   "4N23W\\xa0" carries a non-breaking space.
3. A mooring that stopped being OPERATIONAL kept its last reading forever,
   because the sync only ever rewrote operational rows.

The NDBC fixtures below are verbatim from the live files of 2026-10-01.
"""
import math

import httpx
import pytest

from ingestion import ndbc_realtime as nd
from ingestion import pmel_erddap as pm

# Verbatim, ndbc.noaa.gov/data/realtime2/15009.txt, 2026-10-01.
REALTIME2_15009 = (
    "#YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP  DEWP  VIS PTDY  TIDE\n"
    "#yr  mo dy hr mn degT m/s  m/s     m   sec   sec degT   hPa  degC  degC  degC  nmi  hPa    ft\n"
    "2026 10 01 09 00 188  3.3   MM    MM    MM    MM  MM 1016.2  24.9  26.0    MM   MM   MM    MM\n"
    "2026 10 01 08 00 185  7.9   MM    MM    MM    MM  MM 1015.8  24.8  25.9    MM   MM   MM    MM\n"
)
# First two lines of ndbc.noaa.gov/data/latest_obs/14049.txt, Latin-1 bytes.
LATEST_OBS_14049 = "Station 14049\n12\xb0 0.0' S  65\xb0 0.0' E\n".encode("latin-1")


# ── NDBC ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ref, wmo", [
    ("1500009", "15009"), ("3100006", "31006"), ("4800400", "48400"),
    ("6801014", None),          # 7 digits, no "00" in the middle
    ("TMP3JBVFA1VI6", None), ("4801044", None), ("", None),
])
def test_the_wmo_number_is_read_out_of_the_oceanops_reference(ref, wmo):
    assert nd.wmo_id_from_ref(ref) == wmo


def test_ndbc_position_is_parsed_from_the_latin1_file():
    assert nd.parse_position(LATEST_OBS_14049.decode("latin-1")) == (-12.0, 65.0)
    lat, lon = nd.parse_position("Station 48400\n50\xb0 3.3' N  144\xb0 52.4' W\n")
    assert math.isclose(lat, 50.055) and math.isclose(lon, -144.8733, abs_tol=1e-3)
    assert nd.parse_position("Station 99999\nno position here\n") is None


def test_realtime2_values_come_from_the_header_names():
    obs = nd.parse_realtime2(REALTIME2_15009)
    assert obs == {
        "obs_time": "2026-10-01 09:00Z",
        "wdir": 188.0, "wspd": 3.3, "wvht": None,
        "pres": 1016.2, "atmp": 24.9, "wtmp": 26.0,
    }


def test_a_reordered_header_cannot_move_pressure_into_temperature():
    text = (
        "#YY  MM DD hh mm WTMP PRES\n"
        "#yr  mo dy hr mn degC hPa\n"
        "2026 10 01 09 00 26.0 1016.2\n"
    )
    obs = nd.parse_realtime2(text)
    assert obs["wtmp"] == 26.0 and obs["pres"] == 1016.2


def test_a_row_with_every_value_missing_is_skipped_for_the_next():
    text = REALTIME2_15009.replace(
        "2026 10 01 09 00 188  3.3   MM    MM    MM    MM  MM 1016.2  24.9  26.0",
        "2026 10 01 09 00  MM   MM   MM    MM    MM    MM  MM     MM    MM    MM",
    )
    assert nd.parse_realtime2(text)["obs_time"] == "2026-10-01 08:00Z"


def test_999_hpa_is_a_storm_not_a_missing_value():
    text = "#YY MM DD hh mm PRES\n#yr mo dy hr mn hPa\n2026 10 01 09 00 999.0\n"
    assert nd.parse_realtime2(text)["pres"] == 999.0


def _ndbc_transport(position_text: bytes, realtime: str = REALTIME2_15009):
    def handler(request: httpx.Request) -> httpx.Response:
        if "/latest_obs/" in request.url.path:
            return httpx.Response(200, content=position_text)
        if "/realtime2/" in request.url.path:
            return httpx.Response(200, content=realtime.encode("latin-1"))
        return httpx.Response(404)
    return httpx.MockTransport(handler)


async def test_ndbc_is_asked_by_wmo_number_and_says_which_station_it_was():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if "/latest_obs/" in request.url.path:
            return httpx.Response(200, content="Station 15009\n0\xb0 0.0' N  3\xb0 3.0' W\n".encode("latin-1"))
        return httpx.Response(200, content=REALTIME2_15009.encode())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        obs = await nd.fetch_ndbc_observation(client, "1500009", 0.0, -3.0)
    assert seen == ["/data/latest_obs/15009.txt", "/data/realtime2/15009.txt"]
    assert obs["ndbc_station"] == "15009" and obs["wtmp"] == 26.0


async def test_a_station_ndbc_places_elsewhere_lends_no_reading():
    # 12°S 65°E is where NDBC puts 14049; a mooring we hold at 0°N 3°W is not it.
    async with httpx.AsyncClient(transport=_ndbc_transport(LATEST_OBS_14049)) as client:
        assert await nd.fetch_ndbc_observation(client, "1400049", 0.0, -3.0) is None
        assert await nd.fetch_ndbc_observation(client, "1400049", -12.0, 65.0) is not None


async def test_no_request_is_made_for_a_reference_without_a_wmo_number():
    def handler(request):
        raise AssertionError(f"unexpected request {request.url}")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await nd.fetch_ndbc_observation(client, "6801014", 42.8, 6.0) is None


# ── PMEL ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sid, pos", [
    ("0n3w", (0.0, -3.0)), ("4s80.5e", (-4.0, 80.5)), ("9n140w", (9.0, -140.0)),
    ("12s65e", (-12.0, 65.0)), ("papa", None), ("0n", None),
])
def test_a_pmel_station_id_decodes_to_its_grid_position(sid, pos):
    assert pm.pmel_station_position(sid) == pos


def test_a_name_pmel_spells_differently_is_matched_by_position():
    got = pm.match_pmel_stations([("1500009", "00N03", 0.0, -3.0)], {"0n3w", "0n10w"})
    assert got == {"1500009": "0n3w"}


def test_a_non_breaking_space_does_not_hide_a_name_match():
    # No position, so only the name can match — the position pass would
    # otherwise rescue the station and hide a broken name comparison.
    got = pm.match_pmel_stations([("3100006", "4N23W\xa0", None, None)], {"4n23w"})
    assert got == {"3100006": "4n23w"}


def test_one_pmel_station_feeds_only_the_closest_mooring():
    stations = [("far", "X", 0.4, -3.0), ("near", "Y", 0.05, -3.0)]
    assert pm.match_pmel_stations(stations, {"0n3w"}) == {"near": "0n3w"}


def test_a_name_claim_beats_a_closer_position_claim():
    stations = [("byname", "0N3W", 0.3, -3.0), ("bypos", "SOMETHING", 0.0, -3.0)]
    assert pm.match_pmel_stations(stations, {"0n3w"}) == {"byname": "0n3w"}


def test_a_mooring_a_degree_away_is_not_a_pmel_station():
    assert pm.match_pmel_stations([("r", "X", 1.0, -3.0)], {"0n3w"}) == {}


def test_unpositioned_moorings_are_skipped_not_placed():
    stations = [("nan", "X", float("nan"), -3.0), ("none", "Y", None, None)]
    assert pm.match_pmel_stations(stations, {"0n3w"}) == {}


def test_the_antimeridian_does_not_split_a_match():
    assert pm.match_pmel_stations([("r", "X", 0.0, -179.9)], {"0n180e"}) == {"r": "0n180e"}


# ── The sync, end to end with the network and the database faked ─────────────

class _Conn:
    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    async def fetch(self, sql, *args):
        return self.rows

    async def execute(self, sql, *args):
        self.log.append((" ".join(sql.split()), args))

    async def executemany(self, sql, rows):
        self.log.append((" ".join(sql.split()), list(rows)))

    def transaction(self):
        return _Ctx(None)


class _Ctx:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Ctx(self.conn)


async def test_the_sync_uses_wmo_numbers_position_matching_and_clears_retired_moorings(monkeypatch):
    import db
    from domains import sensors
    from ingestion import oceansites_gdac

    rows = [
        {"ref": "1500009", "name": "00N03",  "lat": 0.0,  "lon": -3.0},    # NDBC by WMO
        {"ref": "9999999", "name": "QQ",     "lat": 0.02, "lon": -110.0},  # PMEL by position
        {"ref": "TMPX",    "name": "OBSEA",  "lat": 41.2, "lon": 1.75},    # nothing anywhere
    ]
    log: list = []
    monkeypatch.setattr(db, "pool", _Pool(_Conn(rows, log)))

    async def fake_ndbc(client, ref, lat, lon):
        return {"obs_time": "2026-10-01 09:00Z", "wtmp": 26.0, "ndbc_station": "15009"} if ref == "1500009" else None

    async def fake_pmel(lookback_days: int = 365):
        return {"0n110w": {"obs_time": "2026-09-30T12:00:00Z", "wtmp": 22.0}}

    async def fake_gdac(names):
        return {}

    async def fake_log_sync(*a, **k):
        return None

    monkeypatch.setattr(nd, "fetch_ndbc_observation", fake_ndbc)
    monkeypatch.setattr(pm, "fetch_pmel_observations", fake_pmel)
    monkeypatch.setattr(oceansites_gdac, "fetch_gdac_observations", fake_gdac)
    monkeypatch.setattr(sensors, "_log_sync", fake_log_sync)

    assert await sensors.sync_oceansites_obs() == 2

    written = {r[0]: r[2] for sql, args in log if "SET latest_obs = $2::jsonb" in sql for r in args}
    assert written == {"1500009": "NDBC", "9999999": "PMEL"}

    cleared = [args[0] for sql, args in log if "WHERE ref = ANY" in sql]
    assert cleared == [["TMPX"]]

    retired = [sql for sql, _ in log if "status <> 'OPERATIONAL'" in sql]
    assert len(retired) == 1 and "latest_obs = NULL" in retired[0]
