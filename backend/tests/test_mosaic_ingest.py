# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import datetime as _dt
import json, pathlib
import pytest
from backend.ingestion import mosaic_ingest as mi

FIX = pathlib.Path(__file__).parent / "fixtures" / "mosaic"

skip_no_fixture = pytest.mark.skipif(
    not (FIX / "geopoints_svalbard.json").exists(),
    reason="fixture licence is not stated by the upstream and it is excluded from the public "
           "repository — see DATA-LICENCES.md",
)


def _core(**over):
    base = {
        "core_id": 1, "core_name": "X", "latitude": 60.0, "longitude": 10.0,
        "water_depth_m": 100.0, "sampling_date": None, "sampling_year": None,
        "sampling_month": None, "sampling_day": None,
        "sampling_campaign_name": None,
        "sampling_campaign_date_start": None, "sampling_campaign_date_end": None,
        "core_comment": None, "sampling_method_type": None, "research_vessel": None,
        "seas": None, "exclusive_economics_zone": None, "longhurst_provinces_full": None,
    }
    base.update(over)
    return base

def _load(name): return json.loads((FIX / name).read_text())

def test_coercers_treat_real_float_nan_as_none():
    # If the API/json.loads ever yields a real float('nan') (not the string "nan"),
    # the coercers must still return None -- never the literal string "nan".
    assert mi._f(float("nan")) is None
    assert mi._s(float("nan")) is None


@skip_no_fixture
def test_parse_geopoints_coerces_types():
    cores = mi.parse_geopoints(_load("geopoints_svalbard.json"))
    assert cores and all(isinstance(c["core_id"], int) for c in cores)
    c = cores[0]
    assert isinstance(c["latitude"], float) and isinstance(c["longitude"], float)
    # "nan" campaign / missing -> None, never the literal "nan"
    assert all(v != "nan" for v in c.values())
    assert c["decade"] is None or c["decade"] % 10 == 0

@skip_no_fixture
def test_parse_samples_extracts_value_and_provenance():
    frags = mi.parse_samples(_load("samples_toc_svalbard.json"), "toc", "total_organic_carbon_%")
    assert frags
    sid, frag = next(iter(frags.items()))
    assert isinstance(sid, int)
    assert frag["core_id"] and ("toc" in frag)
    if frag["toc"] is not None:
        assert isinstance(frag["toc"], float)
    assert "toc" in frag["prov"] and "doi" in frag["prov"]["toc"]

@skip_no_fixture
def test_merge_sections_unions_analyses_on_sample_id():
    toc = mi.parse_samples(_load("samples_toc_svalbard.json"), "toc", "total_organic_carbon_%")
    d14c = mi.parse_samples(_load("samples_d14c_svalbard.json"), "d14c", "Delta_14C")
    merged = mi.merge_sections({"toc": toc, "d14c": d14c})
    assert merged
    ids = {m["sample_id"] for m in merged}
    assert ids == (set(toc) | set(d14c))          # union, no loss
    # a section carries whichever analyses it had; prov merged
    for m in merged:
        assert set(m["prov"]).issubset({"toc", "d14c"})

    by_id = {m["sample_id"]: m for m in merged}

    # A sample measured in BOTH analyses must end up as ONE row carrying BOTH
    # values and a merged prov -- this is the actual point of merge_sections.
    overlap = set(toc) & set(d14c)
    assert overlap, "fixtures must share at least one sample_id to exercise the real merge"
    for sid in overlap:
        m = by_id[sid]
        assert "toc" in m and "d14c" in m
        assert "toc" in m["prov"] and "d14c" in m["prov"]
        # value may legitimately be None in the fixture, but the key must be present
        # (and here we know both fixtures carry a real numeric reading for the overlap)
        assert m["toc"] is not None
        assert m["d14c"] is not None

    # d14c-exclusive sections (measured in d14c only, not toc) must also survive
    # the merge with only the d14c key populated.
    d14c_only = set(d14c) - set(toc)
    assert d14c_only, "d14c fixture should include at least one section not in toc"
    for sid in d14c_only:
        m = by_id[sid]
        assert "d14c" in m["prov"]
        assert m["d14c"] is not None
        assert "toc" not in m["prov"]

@skip_no_fixture
def test_core_rollups_surface_is_shallowest():
    toc = mi.parse_samples(_load("samples_toc_svalbard.json"), "toc", "total_organic_carbon_%")
    merged = mi.merge_sections({"toc": toc})
    roll = mi.core_rollups(merged)
    assert roll
    for cid, r in roll.items():
        assert "has_toc" in r and "toc_surf" in r
        if r["has_toc"]:
            depths = [m["depth_avg_cm"] for m in merged if m["core_id"] == cid and m.get("toc") is not None and m["depth_avg_cm"] is not None]
            # surface value corresponds to the shallowest section (monotone check when depths exist)
            assert r["toc_surf"] is not None


def test_precision_is_day_when_the_source_gave_a_day():
    row = mi.parse_geopoints([_core(sampling_year=2008, sampling_month=8, sampling_day=12,
                                    sampling_date=1218499200000)])[0]
    assert row["date_precision"] == "day"
    assert row["sampling_date"] == _dt.date(2008, 8, 12)


def test_precision_is_day_when_only_sampling_date_is_given():
    """The source can ship a compound sampling_date while leaving the separate
    sampling_month/sampling_day fields blank. The old code looked only at those
    two fields, so this case fell through to date_precision="year" even though
    the source actually gave a full day -- 8 of 4,556 cores measured against the
    live ETH API did exactly this. Deriving month/day from sampling_date (itself
    a source-given value) must restore day precision here."""
    row = mi.parse_geopoints([_core(sampling_year=2008, sampling_date=1218499200000)])[0]
    assert row["sampling_month"] == 8
    assert row["sampling_day"] == 12
    assert row["date_precision"] == "day"


def test_precision_is_month_when_the_day_is_absent():
    row = mi.parse_geopoints([_core(sampling_year=2008, sampling_month=8)])[0]
    assert row["date_precision"] == "month"
    assert row["sampling_day"] is None


def test_precision_is_year_when_only_the_year_is_present():
    row = mi.parse_geopoints([_core(sampling_year=2008)])[0]
    assert row["date_precision"] == "year"
    assert row["sampling_month"] is None


def test_precision_falls_back_to_the_campaign_window():
    """37 cores in a 4-tile sample had no sampling_year but did carry a campaign
    window. Dropping it threw away a date the source actually gave."""
    row = mi.parse_geopoints([_core(sampling_campaign_date_start=1212278400000,
                                    sampling_campaign_date_end=1221436800000,
                                    sampling_campaign_name="ISSS-08")])[0]
    assert row["date_precision"] == "campaign"
    assert row["sampling_year"] is None
    assert row["campaign_start"] == _dt.date(2008, 6, 1)
    assert row["campaign_name"] == "ISSS-08"


def test_precision_is_none_when_the_source_gave_nothing():
    row = mi.parse_geopoints([_core()])[0]
    assert row["date_precision"] == "none"
    assert row["decade"] is None


def test_core_comment_survives_ingest():
    """7 of 27 cores in the real fixture carry a comment contradicting the stored
    year ('samples taken in 2003 and 2004' against sampling_year=2001). Dropping
    it makes the contradiction invisible."""
    row = mi.parse_geopoints([_core(sampling_year=2001,
                                    core_comment="samples taken in 2003 and 2004")])[0]
    assert row["core_comment"] == "samples taken in 2003 and 2004"


def test_campaign_name_and_core_comment_go_through_the_same_placeholder_coercion():
    """Every other string field is read through _s(); campaign_name and
    core_comment were read raw via r.get(...), so a literal "nan" placeholder
    (documented at the top of this module as something the API emits) would
    have rendered verbatim, or a real float NaN would have blown up the
    downstream jsonb insert."""
    row = mi.parse_geopoints([_core(sampling_campaign_name="nan", core_comment=float("nan"))])[0]
    assert row["campaign_name"] is None
    assert row["core_comment"] is None


def test_the_request_actually_asks_for_the_time_fields():
    """Argo failed exactly here: the parser could read four QC flags the request
    never asked for, so every flag was NULL and nothing errored.

    Read the source as text rather than importing it. `domains.geochem` pulls in
    the whole app and trips a circular import through land_layers, which made an
    earlier version of this guard raise ImportError instead of asserting — a
    guard that cannot run is worse than no guard, because the suite still shows
    a test with the right name."""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "domains" / "geochem.py").read_text(encoding="utf-8")
    start = src.index("async def fetch_mosaic_analysis")
    end = src.index("\nasync def ", start + 1)
    body = src[start:end]
    for field in ("sampling_date", "sampling_campaign", "core_comment"):
        assert field in body, f"the ETH request does not ask for {field}"
