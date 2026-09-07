# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Seamount snippet copy — the defects it must not be able to reintroduce.

594 indexed seamount pages shared one description that varied only in digits,
converted at 0.8 % CTR from position 7.9, and asserted "Biodiversity hotspot and
potential cobalt-crust mining target" on every one of them with no per-feature
evidence.

The tests that matter here assert **inequality** and **absence**. A presence
check ("the description mentions the height") would have passed happily against
the broken template — that is exactly how it survived 594 pages.
"""

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from domains.seo import (  # noqa: E402
    _DESCRIPTION_BUDGET,
    _TITLE_BUDGET,
    _seamount_description,
    _seamount_title,
)

# Two real seamounts at very different coordinates, same shape of data.
ARCTIC = dict(height=2713, summit_depth=2242, area_km2=433.4, basin="Arctic Ocean")
PACIFIC = dict(height=2713, summit_depth=2242, area_km2=433.4, basin="Pacific Ocean")


def _desc(d, in_conc=False):
    return _seamount_description(d["height"], d["summit_depth"], d["area_km2"], d["basin"], in_conc)


def test_different_locations_give_different_descriptions():
    """DoD 1 — inequality, not presence.

    These two inputs are IDENTICAL except for the basin. If the copy ever
    collapses back to a coordinate-blind template, this is the test that fails;
    a presence assertion would not notice.
    """
    assert _desc(ARCTIC) != _desc(PACIFIC)
    assert _seamount_title(1204898, 2713, "Arctic Ocean", False) != _seamount_title(
        1204898, 2713, "Pacific Ocean", False
    )


def test_unknown_basin_omits_the_location_clause_entirely():
    """DoD 2 — no "undefined", no placeholder, no guessed basin."""
    d = _seamount_description(2713, 2242, 433.4, None, False)
    assert "in the" not in d
    for placeholder in ("None", "undefined", "null", "Unknown", "N/A"):
        assert placeholder not in d
    # It must still be a usable sentence, not a stub.
    assert d.startswith("A 2,713 m seamount")
    assert "2,242 m" in d


def test_no_unverified_biodiversity_or_mining_claims():
    """DoD 3 — the assertion that was printed 594 times without evidence."""
    banned = ("biodiversity hotspot", "cobalt-crust", "mining target")
    for in_conc in (True, False):
        for d in (ARCTIC, PACIFIC):
            text = _desc(d, in_conc).lower()
            for phrase in banned:
                assert phrase not in text, f"{phrase!r} reintroduced"


def test_concession_claim_is_proximity_not_containment():
    """`in_concession` is ST_DWithin(10 km) — it does not mean "inside"."""
    text = _desc(ARCTIC, in_conc=True)
    assert "Within 10 km of an ISA mining concession." in text
    assert "located within an active" not in text.lower()
    # And absent entirely when the flag is false.
    assert "ISA" not in _desc(ARCTIC, in_conc=False)


@pytest.mark.parametrize(
    "peak_id,height,basin,in_conc",
    [
        (1204898, 2713, "Arctic Ocean", False),
        (9999999, 12345, "Mediterranean Sea", True),   # longest realistic combination
        (1, None, None, False),                         # sparsest possible row
        (4957265, 1720, "Southern Ocean", True),
    ],
)
def test_title_fits_the_serp_budget(peak_id, height, basin, in_conc):
    """DoD 4 — degrade by dropping a clause, never by being truncated."""
    t = _seamount_title(peak_id, height, basin, in_conc)
    assert len(t) <= _TITLE_BUDGET, f"{len(t)} chars: {t}"
    assert t.endswith(" | Abyssal Claims")
    assert f"#{peak_id}" in t
    assert not t.rstrip(" | Abyssal Claims").endswith(",")


@pytest.mark.parametrize("in_conc", [True, False])
@pytest.mark.parametrize("basin", ["Arctic Ocean", "Mediterranean Sea", None])
def test_description_fits_and_never_ends_mid_clause(basin, in_conc):
    d = _seamount_description(12345, 9999, 98765.4, basin, in_conc)
    assert len(d) <= _DESCRIPTION_BUDGET, f"{len(d)} chars: {d}"
    assert d.endswith(".")
    assert ", ." not in d and ",." not in d


def test_related_links_are_optional_and_default_to_nothing():
    """A seamount with no genuine neighbour must render no related block.

    Defaults matter here beyond tidiness: `nearby_seamounts` defaulting to `[]`
    rather than being required is what lets the renderer say "if the list is
    empty, omit the section" instead of inventing filler — and it keeps a
    response replayed from before this field existed valid.
    """
    from domains.seo import SeamountSeo, SeoMeta

    m = SeamountSeo(
        meta=SeoMeta(title="t", description="d", canonical_url="u", json_ld={}),
        peak_id=1, height_m=None, summit_depth_m=None, area_km2=None,
        in_concession=False, latitude=0.0, longitude=0.0,
    )
    assert m.nearby_seamounts == []
    assert m.nearby_concession is None


def test_neighbour_radius_stays_at_the_measured_value():
    """100 km and 10 km are measured thresholds, not round numbers.

    Nearest-neighbour distance over a 400-seamount sample: p50 6.1 km,
    p90 44.6 km, p99 138.5 km — so 100 km leaves 2.2 % of seamounts correctly
    with no neighbours. The concession radius must stay 10 km because
    `in_concession` is defined by that same ST_DWithin: a widened link query
    would show a concession the boolean says is not there.
    """
    import inspect

    from domains.seo import seo_seamount

    src = inspect.getsource(seo_seamount)
    assert src.count("100000") == 1, "the neighbour radius changed"
    assert src.count("10000)") == 2, "the concession radius must match in_concession"


def test_missing_measurements_do_not_produce_broken_copy():
    """Height, summit depth and area are all nullable in the source census."""
    d = _seamount_description(None, None, None, "Pacific Ocean", False)
    assert d.startswith("A seamount in the Pacific Ocean")
    assert "None" not in d and ", ." not in d
    t = _seamount_title(42, None, "Pacific Ocean", False)
    assert "None" not in t and len(t) <= _TITLE_BUDGET
