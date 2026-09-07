# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The gate's comparison logic is what licenses every code move in this
refactor, so it is tested directly rather than trusted."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.refactor_gate import diff_surface


def _surface(**over):
    base = {
        "routes": ["GET /v1/map/claims", "GET /v1/map/vents"],
        "openapi": {"paths": {"/v1/map/claims": {"get": {"summary": "s"}}}},
        "sync_sources": ["cables", "obis"],
        "source_to_action": ["cables"],
    }
    base.update(over)
    return base


def test_identical_surfaces_produce_no_diff():
    assert diff_surface(_surface(), _surface()) == []


def test_removed_route_is_reported():
    after = _surface(routes=["GET /v1/map/claims"])
    diffs = diff_surface(_surface(), after)
    assert any("v1/map/vents" in d for d in diffs), diffs


def test_added_route_is_reported():
    after = _surface(routes=["GET /v1/map/claims", "GET /v1/map/vents", "GET /new"])
    diffs = diff_surface(_surface(), after)
    assert any("/new" in d for d in diffs), diffs


def test_changed_openapi_detail_is_reported():
    after = _surface(openapi={"paths": {"/v1/map/claims": {"get": {"summary": "CHANGED"}}}})
    diffs = diff_surface(_surface(), after)
    assert any("openapi" in d.lower() for d in diffs), diffs


def test_dropped_sync_source_is_reported():
    after = _surface(sync_sources=["cables"])
    diffs = diff_surface(_surface(), after)
    assert any("obis" in d for d in diffs), diffs


def test_route_order_alone_is_not_a_difference():
    """Moving endpoints into a router changes registration order. Order is not
    part of the contract; the set of routes is."""
    after = _surface(routes=["GET /v1/map/vents", "GET /v1/map/claims"])
    assert diff_surface(_surface(), after) == []


def test_duplicate_route_is_reported():
    """The most probable implementer mistake in this refactor: copy an
    endpoint into a router but forget to delete the original `@app.get`,
    double-registering the path. Set arithmetic is blind to this; count
    comparison is not."""
    after = _surface(routes=["GET /v1/map/claims", "GET /v1/map/vents", "GET /v1/map/vents"])
    diffs = diff_surface(_surface(), after)
    assert diffs, diffs
    assert any("v1/map/vents" in d for d in diffs), diffs


def test_dropped_duplicate_is_reported():
    """The reverse direction: two legitimate registrations collapse to one
    (e.g. a duplicate accidentally deleted along with the original)."""
    before = _surface(routes=["GET /v1/map/claims", "GET /v1/map/vents", "GET /v1/map/vents"])
    diffs = diff_surface(before, _surface())
    assert diffs, diffs
    assert any("v1/map/vents" in d for d in diffs), diffs
