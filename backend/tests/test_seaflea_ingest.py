# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import json
from pathlib import Path
from backend.ingestion.seaflea_ingest import build_seep_rows, _parse_depth, _parse_year, _derive_types

FIXTURE = Path(__file__).parent / "fixtures" / "seaflea" / "seaflea_sample.geojson"


def _rows():
    gj = json.loads(FIXTURE.read_text())
    return {r["ext_id"]: r for r in build_seep_rows(gj)}


def test_row_count_and_ids():
    rows = _rows()
    assert set(rows) == {"1.1", "14.4", "2.37", "2.27", "5.1"}


def test_pockmark_dimensions():
    rows = _rows()
    # 5.1 carries real pockmark morphometry (depth stored negative in source)
    pm = rows["5.1"]
    assert pm["pockmark_depth_m"] == -3.0
    assert pm["pockmark_radius_m"] == 106.0
    # a pockmark without PM dims (and any non-pockmark) → None
    assert rows["14.4"]["pockmark_depth_m"] is None
    assert rows["14.4"]["pockmark_radius_m"] is None
    assert rows["1.1"]["pockmark_depth_m"] is None


def test_pure_single_type():
    r = _rows()["1.1"]
    assert r["lat"] == 40.5697872700001 and r["lon"] == -69.8706429599999
    assert r["depth_m"] == 58.6
    assert r["obs_year"] == 2012
    assert r["feature_types"] == ["gas_bubbles"]
    assert r["primary_type"] == "gas_bubbles"
    assert r["type_raw"] == {"gas_bubbles": "Bubbles"}
    assert r["source_url"] == "https://www.nature.com/articles/ngeo2232"


def test_multi_flag_priority_and_empty_depth_year():
    r = _rows()["14.4"]
    # priority: gas_bubbles > pockmark > chem_community
    assert r["feature_types"] == ["gas_bubbles", "pockmark", "chem_community"]
    assert r["primary_type"] == "gas_bubbles"
    assert r["depth_m"] is None      # empty string -> None
    assert r["obs_year"] is None     # null -> None
    assert r["source_url"] is None   # empty string -> None


def test_uncertain_variants_fold_to_base_type():
    chem = _rows()["2.37"]
    assert chem["feature_types"] == ["chem_community"]
    assert chem["type_raw"] == {"chem_community": "U(mat/biofuzz on clams?)"}
    hard = _rows()["2.27"]
    assert hard["feature_types"] == ["hardground"]
    assert hard["primary_type"] == "hardground"


def test_helpers():
    assert _parse_depth("58.6") == 58.6
    assert _parse_depth("") is None
    assert _parse_depth("n/a") is None
    assert _parse_year(0) is None
    assert _parse_year(None) is None
    assert _parse_year(2012) == 2012
    types, primary, raw = _derive_types({"Gas_Bubbles": "Bubbles", "Pockmark": "Pockmarks"})
    assert types == ["gas_bubbles", "pockmark"] and primary == "gas_bubbles"
