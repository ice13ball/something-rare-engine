# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import pytest
from backend import profiles


def test_seed_layers_are_all_known():
    known = profiles.KNOWN_LAYER_IDS
    for p in profiles.PROFILE_SEED:
        for lid in p["layers"]:
            assert lid in known, f"seed {p['id']} references unknown layer {lid!r}"


def test_seed_rows_validate():
    for p in profiles.PROFILE_SEED:
        profiles.validate_profile(p, profiles.KNOWN_LAYER_IDS)  # must not raise


def test_seed_sections_and_labels():
    for p in profiles.PROFILE_SEED:
        assert p["section"] in ("ocean", "land")
        assert p["label"].get("en"), f"{p['id']} missing en label"


def test_validate_rejects_unknown_layer():
    row = {"id": "x", "section": "ocean", "order_idx": 1,
           "layers": ["contracts", "not-a-layer"],
           "label": {"en": "X"}, "description": {}, "accent": None}
    with pytest.raises(ValueError, match="unknown layer"):
        profiles.validate_profile(row, profiles.KNOWN_LAYER_IDS)


def test_validate_rejects_bad_section():
    row = {"id": "x", "section": "sky", "order_idx": 1, "layers": ["contracts"],
           "label": {"en": "X"}, "description": {}, "accent": None}
    with pytest.raises(ValueError, match="section"):
        profiles.validate_profile(row, profiles.KNOWN_LAYER_IDS)


def test_validate_rejects_empty_layers():
    row = {"id": "x", "section": "ocean", "order_idx": 1, "layers": [],
           "label": {"en": "X"}, "description": {}, "accent": None}
    with pytest.raises(ValueError, match="at least one layer"):
        profiles.validate_profile(row, profiles.KNOWN_LAYER_IDS)


def test_validate_rejects_missing_en_label():
    row = {"id": "x", "section": "ocean", "order_idx": 1, "layers": ["contracts"],
           "label": {"pl": "X"}, "description": {}, "accent": None}
    with pytest.raises(ValueError, match="en label"):
        profiles.validate_profile(row, profiles.KNOWN_LAYER_IDS)


def test_validate_rejects_bad_slug():
    row = {"id": "Bad Slug!", "section": "ocean", "order_idx": 1, "layers": ["contracts"],
           "label": {"en": "X"}, "description": {}, "accent": None}
    with pytest.raises(ValueError, match="slug"):
        profiles.validate_profile(row, profiles.KNOWN_LAYER_IDS)


import os
import asyncpg

DB_URL = os.environ.get("DATABASE_URL")
pytestmark_db = pytest.mark.skipif(not DB_URL, reason="requires DATABASE_URL")


@pytestmark_db
@pytest.mark.asyncio
async def test_seed_creates_rows():
    conn = await asyncpg.connect(DB_URL)
    try:
        await conn.execute(profiles.STARTUP_PROFILES_DDL)
        await conn.executemany(
            """INSERT INTO startup_profiles
                 (id, section, order_idx, status, layers, label, description, accent)
               VALUES ($1,$2,$3,'enabled',$4,$5::jsonb,$6::jsonb,$7)
               ON CONFLICT (id) DO NOTHING""",
            [(p["id"], p["section"], p["order_idx"], p["layers"],
              __import__("json").dumps(p["label"]),
              __import__("json").dumps(p["description"]), p.get("accent"))
             for p in profiles.PROFILE_SEED],
        )
        n = await conn.fetchval("SELECT count(*) FROM startup_profiles WHERE id = ANY($1)",
                                [p["id"] for p in profiles.PROFILE_SEED])
        assert n == len(profiles.PROFILE_SEED)
    finally:
        await conn.close()


try:
    from backend import main as _main_mod  # imports app; needs deps installed
    _main_import_error = None
except ImportError as e:  # pragma: no cover - env-dependent
    _main_mod = None
    _main_import_error = e


@pytest.mark.skipif(
    _main_mod is None,
    reason=f"backend.main import failed (missing deps in this runner): {_main_import_error}",
)
def test_serialize_profiles_shape():
    import json

    rows = [{
        "id": "seabed-mining", "section": "ocean", "order_idx": 10,
        "layers": ["contracts", "apeis"],
        "label": json.dumps({"en": "Seabed Mining", "pl": "Górnictwo"}),
        "description": json.dumps({"en": "desc"}), "accent": None,
        "views": None,
    }]
    out = json.loads(_main_mod.serialize_profiles(rows))
    assert out[0]["id"] == "seabed-mining"
    assert out[0]["layers"] == ["contracts", "apeis"]
    assert out[0]["label"]["pl"] == "Górnictwo"     # JSONB string decoded to dict
    assert out[0]["section"] == "ocean"
    assert out[0]["views"] == {}


try:
    from backend.routers import admin_profiles_api as _ap_mod
    _ap_import_error = None
except ImportError as e:  # pragma: no cover - env-dependent
    _ap_mod = None
    _ap_import_error = e


@pytest.mark.skipif(
    _ap_mod is None,
    reason=f"backend.routers.admin_profiles_api import failed (missing deps in this runner): {_ap_import_error}",
)
def test_admin_body_to_row_validates():
    ap = _ap_mod
    good = ap._ProfileBody(id="x-test", section="ocean", order_idx=5,
                           layers=["contracts"], label={"en": "X"},
                           description={}, accent=None)
    ap._validate_body(good)  # must not raise
    bad = ap._ProfileBody(id="x-test", section="ocean", order_idx=5,
                          layers=["nope"], label={"en": "X"},
                          description={}, accent=None)
    with pytest.raises(Exception):
        ap._validate_body(bad)


def test_sanitize_views_keeps_only_profile_layers():
    v = {"geotraces": {"element": "fe"}, "argo": {"x": 1}, "not-in-profile": {"a": 1}}
    assert profiles.sanitize_views(v, ["geotraces", "argo"]) == {
        "geotraces": {"element": "fe"}, "argo": {"x": 1}}


def test_sanitize_views_non_dict_returns_empty():
    assert profiles.sanitize_views("x", ["a"]) == {}
    assert profiles.sanitize_views(None, ["a"]) == {}


def test_sanitize_views_drops_non_dict_field_values():
    assert profiles.sanitize_views({"geotraces": "bad"}, ["geotraces"]) == {}


def test_sanitize_views_empty_layers():
    assert profiles.sanitize_views({"geotraces": {"element": "fe"}}, []) == {}


@pytest.mark.skipif(
    _main_mod is None,
    reason=f"backend.main import failed (missing deps in this runner): {_main_import_error}",
)
def test_serialize_profiles_includes_views():
    import json
    from backend import main

    rows = [{
        "id": "carbon-acidification", "section": "ocean", "order_idx": 30,
        "layers": ["marine-carbon", "geotraces"],
        "label": json.dumps({"en": "Carbon"}), "description": json.dumps({"en": "d"}),
        "accent": None,
        "views": json.dumps({"geotraces": {"element": "fe", "displayMode": "hexes"}}),
    }]
    out = json.loads(main.serialize_profiles(rows))
    assert out[0]["views"]["geotraces"]["displayMode"] == "hexes"
