# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The station endpoint must return what the station panel reads.

`GeotracesStationPanel` renders five rows from the station rollup — the
sampling date, the sample count and the three depth figures — and every one is
gated on `!= null`. The `/by-id` SELECT listed sixteen columns and none of
those five, so all five rendered nothing on every one of the 3,874 stations.

Measured on production 2026-09-10, which is what makes it a defect rather than
an absence: sample_time 100%, n_samples 100%, min_depth_m 100%,
max_depth_m 100%, bottom_depth_m 99.7% populated. Data we had, stored, and hid.

⛔ This is checked structurally rather than over HTTP because the failure is a
mismatch between a SELECT list and a set of property reads — a live call would
prove it too, but only for whichever station happened to be queried, and only
while the database is reachable.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
ROUTER = ROOT / "backend" / "routers" / "spatial_v2.py"
PANEL = ROOT / "frontend" / "src" / "components" / "panels" / "arctic" / "GeotracesStationPanel.tsx"

#: The rollup columns the panel renders. Names must match the DB columns.
STATION_ROLLUP_FIELDS = (
    "sample_time", "n_samples", "min_depth_m", "max_depth_m", "bottom_depth_m",
)


def _station_select() -> str:
    """The SELECT that feeds the `station` key of the /by-id response."""
    src = ROUTER.read_text(encoding="utf-8")
    m = re.search(r"SELECT([^\"]*?)FROM geotraces_stations WHERE station_id", src, re.S)
    assert m, "fixture problem: the geotraces_stations SELECT moved or was renamed"
    return m.group(1)


def test_the_panel_really_does_read_these_fields():
    """⛔ The fixture assertion. If the panel stopped reading them, the test
    below would pass on a SELECT that serves nobody."""
    panel = PANEL.read_text(encoding="utf-8")
    missing = [f for f in STATION_ROLLUP_FIELDS if f"station.{f}" not in panel]
    assert not missing, (
        "these are no longer read by GeotracesStationPanel, so this file is "
        f"guarding a contract that no longer exists: {missing}"
    )


def test_every_field_the_panel_reads_is_selected():
    sel = _station_select()
    missing = [f for f in STATION_ROLLUP_FIELDS if not re.search(rf"\b{f}\b", sel)]
    assert not missing, (
        "GeotracesStationPanel renders these and the endpoint does not return "
        f"them, so each is a permanently blank row on every station: {missing}"
    )


def test_the_station_timestamp_is_serialised_for_json():
    """asyncpg returns a datetime; the panel and every API consumer want ISO.
    The per-sample rows already did this — the rollup never did, because it was
    never selected."""
    src = ROUTER.read_text(encoding="utf-8")
    m = re.search(r"    d = dict\(st\)(.{0,400})", src, re.S)
    assert m, "fixture problem: the station dict is no longer built with dict(st)"
    assert 'd["sample_time"].isoformat()' in m.group(1), (
        "the station rollup timestamp reaches JSON as a raw datetime"
    )
