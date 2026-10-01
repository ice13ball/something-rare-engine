# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""unified-point 'status' key — arag_horizon / arag_horizon_shift disclose WHY they are
null (an always-supersaturated column, or no horizon to shift) instead of collapsing to
a bare 'no data here', while every other variable's status stays null and every value is
unchanged. See CLAUDE.md task 2026-09-29."""

import asyncio
import json
import math

import pytest
from domains.fields import carbon
from services import marine_carbon


def _sampled_all_ordinary(inf_horizon: bool):
    """Values mc_sample() would return for every var — ordinary numbers everywhere,
    except arag_horizon/arag_horizon_shift already coerced to None by mc_sample's own
    non-finite guard (mirrors production: the raw inf never reaches `sampled`)."""
    out = {}
    for k in marine_carbon.MARINE_CARBON_VARS:
        if k in ("arag_horizon", "arag_horizon_shift"):
            out[k] = None if inf_horizon else 42.0
        elif k == "substrate":
            out[k] = None
        else:
            out[k] = 1.0
    return out


def _run_unified_point(monkeypatch, inf_horizon: bool):
    sampled = _sampled_all_ordinary(inf_horizon)
    monkeypatch.setattr(carbon, "mc_sample",
                         lambda k, lat, lon, depth, _oxy_grid=None: sampled[k])
    monkeypatch.setattr(carbon.oxygen_deox, "load_recent_grid", lambda: None)

    raw_horizon = math.inf if inf_horizon else 1234.5

    def fake_sample(var, lat, lon, depth):
        assert var == "horizon"
        return raw_horizon
    monkeypatch.setattr(carbon.acidification, "sample", fake_sample)

    resp = asyncio.run(carbon.carbon_unified_point(lat=10.0, lon=20.0, depth=2000.0))
    return json.loads(resp.body)


def _status_of(payload, key):
    for g in payload["groups"]:
        for v in g["variables"]:
            if v["key"] == key:
                return v
    raise AssertionError(f"{key} not found in payload")


def test_infinite_horizon_sets_both_statuses_and_nulls_the_values(monkeypatch):
    payload = _run_unified_point(monkeypatch, inf_horizon=True)

    horizon = _status_of(payload, "arag_horizon")
    assert horizon["status"] == "column_supersaturated"
    assert horizon["value"] is None

    shift = _status_of(payload, "arag_horizon_shift")
    assert shift["status"] == "no_horizon"
    assert shift["value"] is None


def test_infinite_horizon_leaves_every_other_status_null(monkeypatch):
    payload = _run_unified_point(monkeypatch, inf_horizon=True)
    for g in payload["groups"]:
        for v in g["variables"]:
            if v["key"] in ("arag_horizon", "arag_horizon_shift"):
                continue
            assert v["status"] is None, v["key"]
            # ordinary values pass through unchanged
            if v["key"] != "substrate":
                assert v["value"] == 1.0


def test_finite_horizon_both_statuses_null_and_values_present(monkeypatch):
    payload = _run_unified_point(monkeypatch, inf_horizon=False)

    horizon = _status_of(payload, "arag_horizon")
    assert horizon["status"] is None
    assert horizon["value"] == 42.0

    shift = _status_of(payload, "arag_horizon_shift")
    assert shift["status"] is None
    assert shift["value"] == 42.0


def test_group_point_statuses_default_to_none_when_omitted():
    # hexes never pass statuses — group_point must still be safe/additive
    out = marine_carbon.group_point({"omega_arag": 1.2})
    row = next(v for g in out for v in g["variables"] if v["key"] == "omega_arag")
    assert row["status"] is None


def test_group_point_statuses_pass_through_only_named_keys():
    out = marine_carbon.group_point(
        {"arag_horizon": None, "omega_arag": 1.2},
        statuses={"arag_horizon": "column_supersaturated"},
    )
    horizon = next(v for g in out for v in g["variables"] if v["key"] == "arag_horizon")
    omega = next(v for g in out for v in g["variables"] if v["key"] == "omega_arag")
    assert horizon["status"] == "column_supersaturated"
    assert omega["status"] is None
