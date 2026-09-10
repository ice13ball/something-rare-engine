# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""We may not add a fact ONC did not give us.

The portal mirrors its sources 1:1 (Michal, 2026-09-10): ONC's values are never
modified, nothing is filtered out — and by the same rule, nothing is invented.
`onc_ctd_profiles.cast_time` was invented. It is the first pressure sample
inside the 7-day window WE request, so on production it sat exactly 7.00 days
before every sync, on all 84 rows, and the chart printed it as "Cast: <t> UTC".

Nor are these casts. Measured on production 2026-09-10:

    RCNW4     10,080 samples across 1968.3 - 1969.5 m   (1.2 m)
    PVIP.C1  100,000 samples across   98.1 -   98.2 m   (0.1 m)
    27 of 28 device-locations span under 5 m of pressure

They are moored instruments at a fixed depth. The fix adds ONC's own figures —
the window's first and last sample, the sample count, the depth range — so the
panel can show what ONC covered. ⛔ No device is excluded and no value is
recomputed; the sampler still stores every number ONC returns.
"""
import ast
import pathlib
import re

ONC    = pathlib.Path(__file__).resolve().parents[1] / "domains" / "onc.py"
SCHEMA = pathlib.Path(__file__).resolve().parents[1] / "schema" / "onc.py"

#: ONC's own figures, added 2026-09-10. Every one must survive the round trip
#: from the sync, through the table, to the endpoint's response.
WINDOW_FIELDS = ("sample_start", "sample_end", "n_samples", "depth_min_m", "depth_max_m")


def _slice(src: str, start_marker: str, end_marker: str) -> str:
    i = src.index(start_marker)
    return src[i:src.index(end_marker, i + len(start_marker))]


def test_the_fixture_isolated_both_halves():
    src = ONC.read_text(encoding="utf-8")
    sync = _slice(src, "async def sync_onc_ctd_profiles", "\n# ── ONC CTD archive")
    api  = _slice(src, '@router.get("/v1/onc/ctd/', "@router.get(\"/v1/onc/earthquakes-near")
    assert len(sync) > 500 and len(api) > 300, (
        "fixture problem: sync or endpoint not sliced out — every assertion "
        "below would search the wrong text"
    )


def test_the_table_has_somewhere_to_put_them():
    ddl = SCHEMA.read_text(encoding="utf-8")
    missing = [f for f in WINDOW_FIELDS if f not in ddl]
    assert not missing, f"onc_ctd_profiles has no column for: {missing}"
    # Idempotent, because the VPS re-runs the schema on every deploy.
    for f in WINDOW_FIELDS:
        assert re.search(rf"ADD COLUMN IF NOT EXISTS {f}\b", ddl), (
            f"{f} is added without IF NOT EXISTS — the next deploy raises"
        )


def test_the_sync_writes_oncs_own_numbers():
    # ⛔ End at the archive banner, not the USGS one: sync_onc_ctd_series was
    # added between them on 2026-09-10 and the old slice swallowed it, so this
    # file's guards started reading a function they were never written for.
    sync = _slice(ONC.read_text(encoding="utf-8"),
                  "async def sync_onc_ctd_profiles", "\n# ── ONC CTD archive")
    missing = [f for f in WINDOW_FIELDS if f not in sync]
    assert not missing, f"sync_onc_ctd never stores: {missing}"
    # ⚠️ sample_end must come from ONC's LAST sample time, not be derived from
    # anything of ours. If this stops reading the array, the window collapses
    # back to a single timestamp of our own choosing.
    assert 'p_times[-1]' in sync, (
        "sample_end is no longer read off ONC's own sampleTimes array"
    )


def test_the_endpoint_returns_every_one_of_them():
    # ⛔ Check 24d. Five GEOTRACES columns were 100% populated and absent from
    # the /by-id SELECT; every panel rendered five blank rows for months.
    api = _slice(ONC.read_text(encoding="utf-8"),
                 '@router.get("/v1/onc/ctd/', '@router.get("/v1/onc/earthquakes-near')
    select = api[api.index("SELECT"):api.index("location_code,\n", api.index("SELECT")) + 400]
    for f in WINDOW_FIELDS:
        assert f in select, f"the /v1/onc/ctd SELECT does not fetch {f}"
        assert f'"{f}"' in api, f"the /v1/onc/ctd response does not carry {f}"


def test_nothing_filters_devices_out_by_their_depth_range():
    # The 1:1 rule cuts both ways: a fixed-depth instrument is still ONC data
    # and stays on the map. Dropping the 27 flat ones would be a modification.
    # ⛔ End at the archive banner, not the USGS one: sync_onc_ctd_series was
    # added between them on 2026-09-10 and the old slice swallowed it, so this
    # file's guards started reading a function they were never written for.
    sync = _slice(ONC.read_text(encoding="utf-8"),
                  "async def sync_onc_ctd_profiles", "\n# ── ONC CTD archive")
    tree = ast.parse("async def f():\n" + "\n".join(
        "    " + ln for ln in sync.splitlines()[1:]))
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            text = ast.unparse(node)
            assert not ("depth_max_m" in text and "depth_min_m" in text), (
                f"a depth-span comparison decides something in sync_onc_ctd: "
                f"{text!r} — that would filter ONC's own instruments"
            )
