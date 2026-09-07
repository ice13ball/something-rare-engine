# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""`basin_for` must be right where it answers and silent where it would guess.

The value of this function is entirely in the second half. A basin printed on a
public page is a factual claim; a wrong one is worse than none, because the page
now says something false about a real place. So every test here that asserts
`None` is as load-bearing as the ones that assert a name.
"""

import pytest

from backend.ocean_basin import basin_for


@pytest.mark.parametrize(
    "lat,lon,expected,why",
    [
        # Poles — the two definition-driven cases.
        (83.92, -3.00, "Arctic Ocean", "north of the Arctic Circle"),
        (66.6, -170.0, "Arctic Ocean", "just inside the circle"),
        (-64.0, 0.0, "Southern Ocean", "south of 60S"),
        (-61.0, -140.0, "Southern Ocean", "60S applies at every longitude"),
        # Atlantic.
        (30.0, -40.0, "Atlantic Ocean", "mid-Atlantic ridge, north"),
        (-30.0, -20.0, "Atlantic Ocean", "South Atlantic"),
        (25.0, -90.0, "Atlantic Ocean", "Gulf of Mexico is Atlantic, not Pacific"),
        (0.0, -30.0, "Atlantic Ocean", "equatorial Atlantic"),
        (-35.0, 18.0, "Atlantic Ocean", "west of the Agulhas meridian"),
        # Indian.
        (-35.0, 22.0, "Indian Ocean", "east of the Agulhas meridian"),
        (-20.0, 80.0, "Indian Ocean", "central Indian"),
        (-40.0, 140.0, "Indian Ocean", "west of the Tasmania meridian"),
        (0.0, 60.0, "Indian Ocean", "Arabian Sea side"),
        # Pacific.
        (0.0, -140.0, "Pacific Ocean", "central Pacific"),
        (-40.0, 150.0, "Pacific Ocean", "east of the Tasmania meridian"),
        (20.0, 170.0, "Pacific Ocean", "north-west Pacific"),
        (-20.0, -100.0, "Pacific Ocean", "south-east Pacific, west of the Chile boundary"),
        (10.0, -100.0, "Pacific Ocean", "off Central America, west of the isthmus"),
        # Mediterranean — without its own box this reads "Atlantic Ocean",
        # which is flatly wrong.
        (38.0, 15.0, "Mediterranean Sea", "Tyrrhenian"),
        (34.0, 25.0, "Mediterranean Sea", "east Mediterranean"),
    ],
)
def test_known_positions(lat, lon, expected, why):
    assert basin_for(lat, lon) == expected, why


@pytest.mark.parametrize(
    "lat,lon,why",
    [
        (0.0, 120.0, "Indonesian archipelago — a polygon problem, not a meridian"),
        (-5.0, 110.0, "same transition zone"),
        (45.0, 60.0, "central Asia: land, so almost certainly bad data"),
        (91.0, 0.0, "latitude out of range"),
        (0.0, 200.0, "longitude out of range"),
        (None, 10.0, "missing latitude"),
        (10.0, None, "missing longitude"),
        ("n/a", 10.0, "non-numeric input must not raise"),
    ],
)
def test_abstains_rather_than_guesses(lat, lon, why):
    assert basin_for(lat, lon) is None, why


def test_never_returns_an_empty_or_placeholder_string():
    """A falsy-but-not-None return would slip past `if basin:` guards."""
    for lat in range(-90, 91, 5):
        for lon in range(-180, 181, 5):
            got = basin_for(float(lat), float(lon))
            assert got is None or (isinstance(got, str) and got.strip())
            assert got not in ("", "undefined", "None", "Unknown")
