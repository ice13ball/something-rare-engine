# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import json
from pathlib import Path

from backend.ingestion.worms_ingest import (
    normalize_name, pick_best_candidate, resolution_from_candidate, worms_row_from_record,
)

FIX = Path(__file__).parent / "fixtures" / "worms"


def _load(name):
    return json.loads((FIX / name).read_text())


def test_normalize_name_trims_and_collapses():
    assert normalize_name("  Munidopsis   sp. ") == "Munidopsis sp."
    assert normalize_name("Munida") == "Munida"


def test_pick_best_prefers_exact_over_fuzzy():
    cands = [
        {"AphiaID": 2, "match_type": "phonetic"},
        {"AphiaID": 1, "match_type": "exact"},
        {"AphiaID": 3, "match_type": "like"},
    ]
    assert pick_best_candidate(cands)["AphiaID"] == 1


def test_pick_best_empty_is_none():
    assert pick_best_candidate([]) is None
    assert pick_best_candidate(None) is None


def test_resolution_exact_is_verified_and_uses_valid_id():
    group = _load("match_munidopsis.json")[0]   # list of candidates
    best = pick_best_candidate(group)
    res = resolution_from_candidate("Munidopsis", best)
    assert res["raw_name"] == "Munidopsis"
    assert res["verified"] is (res["match_type"] == "exact")
    # matched id is the VALID id (valid_AphiaID when present, else AphiaID)
    expected = best.get("valid_AphiaID") or best.get("AphiaID")
    assert res["matched_aphia_id"] == expected
    assert isinstance(res["matched_aphia_id"], int)


def test_resolution_no_candidate_is_unverified_none():
    res = resolution_from_candidate("Zzzxqq notataxon", None)
    assert res == {
        "raw_name": "Zzzxqq notataxon",
        "matched_aphia_id": None,
        "match_type": "none",
        "verified": False,
    }


def test_nomatch_fixture_yields_none():
    data = _load("match_nomatch.json")           # [null]
    groups = [(g or []) for g in data]           # mirror match_names normalization
    res = resolution_from_candidate("Zzzxqq notataxon", pick_best_candidate(groups[0]))
    assert res["match_type"] == "none" and res["matched_aphia_id"] is None and res["verified"] is False


def test_worms_row_maps_fields_and_env_flags():
    rec = _load("records_by_ids.json")[0]
    row = worms_row_from_record(rec)
    assert row["aphia_id"] == rec["AphiaID"]
    assert row["scientificname"] == rec["scientificname"]
    assert row["class_name"] == rec.get("class")
    assert row["order_name"] == rec.get("order")
    # env flags pass through as 0/1/None unchanged
    assert row["is_marine"] == rec.get("isMarine")
