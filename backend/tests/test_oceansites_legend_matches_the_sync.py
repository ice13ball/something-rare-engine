# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The legend must describe the sync that actually runs.

Two things drifted apart on `oceansites` and nothing noticed for two days:

1. The 2026-09-08 widening took `oceansites_stations` from 65 OPERATIONAL-only
   rows to the whole OceanOPS register. `/v1/map/oceansites` has no WHERE
   clause, so all of them render. The legend still said "only the ~20 stations
   with active NDBC buoy feeds are shown" — measured 2026-09-10: 1,072 shown.

2. `sync_oceansites_obs` tries NDBC, then PMEL ERDDAP, then the OceanSITES
   GDAC. Only the first was ever named in the legend, and it is the one that
   now wins nothing: obs_source on production was PMEL 49 / GDAC 1 / NDBC 0.
   A reader following the Verify tab was sent to ndbc.noaa.gov to check a
   reading that came from PMEL.

⛔ These two failures are guarded SEPARATELY on purpose. A single test that
happened to trip on the phrase "NDBC" would have gone green the moment the
word appeared anywhere, including in a sentence still claiming NDBC is the
only source.
"""
import json
import pathlib
import re

ROOT     = pathlib.Path(__file__).resolve().parents[2]
SENSORS  = ROOT / "backend" / "domains" / "sensors.py"
LOCALES  = ROOT / "frontend" / "public" / "locales"

#: Every literal `sync_oceansites_obs` can store in `oceansites_stations.obs_source`.
#: Derived from the code so a fourth source cannot be added silently.
_OBS_SOURCE = re.compile(r'obs_by_ref\[ref\]\s*=\s*\([^,]+,\s*"([A-Z]+)"\)|for ref, obs in \w+ if obs')


def _sources_the_sync_can_attribute() -> set[str]:
    src = SENSORS.read_text(encoding="utf-8")
    start = src.index("async def sync_oceansites_obs")
    end   = src.index("\nasync def ", start + 10)
    body  = src[start:end]
    found = set(re.findall(r'\(\s*(?:obs|match|pmel_match|\w+)\s*,\s*"([A-Z]{3,6})"\s*\)', body))
    return found


def _locales() -> list[pathlib.Path]:
    return sorted(p for p in LOCALES.iterdir() if (p / "legend.json").is_file())


def _oceansites_prose(loc: pathlib.Path) -> str:
    d = json.loads((loc / "legend.json").read_text(encoding="utf-8"))
    layer = d["layers"]["oceansitesMoorings"]
    parts = [str(v) for v in layer.values()]
    parts += [d["dates"]["oceansites"], d["dates"]["fresh_oceansites"],
              d["verify"]["oceansites"], d["verify"]["lim_oceansites"]]
    return "\n".join(parts)


def test_the_fixture_finds_more_than_one_source_and_more_than_one_locale():
    # ⛔ Both assertions below iterate. An empty set and an empty locale list
    # would make every one of them pass without comparing anything.
    srcs = _sources_the_sync_can_attribute()
    assert len(srcs) >= 3, f"fixture problem: parsed {srcs!r} from sync_oceansites_obs"
    assert len(_locales()) >= 2, "fixture problem: fewer than two locales discovered"


def test_every_observation_source_the_sync_can_use_is_named_in_every_locale():
    srcs = _sources_the_sync_can_attribute()
    missing = {}
    for loc in _locales():
        gone = sorted(s for s in srcs if s not in _oceansites_prose(loc))
        if gone:
            missing[loc.name] = gone
    assert not missing, (
        "the OceanSITES legend names only some of the sources the sync can "
        f"attribute ({sorted(srcs)}); missing per locale: {missing}. A reader "
        "sent to the wrong portal cannot verify the reading they clicked."
    )


def test_no_locale_claims_the_map_is_restricted_to_stations_that_have_a_feed():
    # The endpoint returns every row. Any wording that promises a filtered map
    # is false, and it is false in the direction that flatters us: it makes a
    # register dump look like a curated set of verified stations.
    claims = re.compile(
        r"only .{0,40}(with (verified|active)|feeds?)|"
        r"tylko .{0,40}(zweryfikowan|aktywn)|"
        r"seules .{0,40}(vérifi|actif|active)|"
        r"nur .{0,40}(verifiziert|aktive)",
        re.IGNORECASE)
    offenders = {}
    for loc in _locales():
        hits = claims.findall(_oceansites_prose(loc))
        if hits:
            offenders[loc.name] = hits
    assert not offenders, (
        "the OceanSITES legend promises a filtered map, but "
        "/v1/map/oceansites filters nothing but rows with NaN coordinates (which "
        "cannot be points) and returned 1,072 of 1,072 rows on 2026-09-10. "
        f"Offending locales: {offenders}"
    )


def test_the_map_endpoint_filters_nothing_but_unpositioned_rows():
    """The legend above may not promise a map restricted to stations that have
    a FEED. This binds the other side: the endpoint may not quietly grow such a
    filter. The only WHERE it is allowed is the positional invariant.

    ⛔ History. This test used to assert "no WHERE at all", and on 2026-09-11
    it went red exactly as its comment promised, when a WHERE arrived that
    excludes rows with NaN coordinates: OceanOPS spells "unknown position" as
    the string "NaN", float() turned 36 of them into real NaN in a NOT NULL
    column, and /v1/map/oceansites shipped a bare NaN that no browser parses.
    Those rows cannot be points and cannot be JSON — excluding them is not
    hiding a station from the reader, it is the table's own contract
    ("one row per base ref, positioned"). The deployments table keeps every
    record with position_flag. A filter on observations or status would still
    be the defect this guard exists for, and still reddens here.
    """
    src = SENSORS.read_text(encoding="utf-8")
    start = src.index('@router.get("/v1/map/oceansites"')
    body  = src[start:src.index("_oceansites_cache = result", start)]
    query = body[body.index("FROM oceansites_stations"):].split("ORDER BY")[0]
    # SQL comments explain the filter; they are not the filter.
    query = "\n".join(ln for ln in query.splitlines() if not ln.strip().startswith("--"))
    where = query.upper().split("WHERE", 1)[1] if "WHERE" in query.upper() else ""

    for col in ("LATEST_OBS", "OBS_SOURCE", "OBS_FETCHED_AT", "STATUS", "NETWORK", "AGE_DAYS", "DEPLOY_DATE"):
        assert col not in where, (
            f"/v1/map/oceansites now filters on {col}. That restricts the map to a "
            "subset the legend does not describe — re-measure and fix the wording first."
        )
    if where:
        # Whatever is there must be about position only.
        stripped = re.sub(r"'NAN'::FLOAT8|LAT|LON|<>|AND|\s|\(|\)", "", where)
        assert stripped == "", (
            f"unexpected WHERE on /v1/map/oceansites: {where.strip()!r} — only the "
            "NaN-coordinate exclusion is allowed here"
        )
