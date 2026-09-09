# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Guards for the pass-through rule — see docs/methods/data-passthrough.md."""
import pytest

from backend.domains.land.hazards import _score_or_none, _concentration_or_none


# WRI Aqueduct's documented no-data code. A 0-5 index score can never be -9999,
# so storing it makes every mean and colour ramp over the column read as
# "very low risk" rather than as an error.
@pytest.mark.parametrize("sentinel", [-9999, -9999.0, "-9999", -999, "-999"])
def test_score_or_none_rejects_the_no_data_code(sentinel):
    assert _score_or_none(sentinel) is None


@pytest.mark.parametrize("good", [0, 0.0, 2.5, 5, "3.7"])
def test_score_or_none_keeps_a_real_score(good):
    assert _score_or_none(good) == float(good)


def test_score_or_none_passes_none_through():
    assert _score_or_none(None) is None


def test_score_or_none_rejects_a_non_numeric_string():
    assert _score_or_none("no data") is None


def test_air_quality_update_coerces_every_pollutant():
    """Every pollutant argument in the readings UPDATE must pass through the
    concentration guard. OpenAQ ships at least -9999, -999, -1111, -995 and -9
    as fill values in these fields, and the readings sync has no coerce
    helper of its own."""
    import inspect
    from backend.domains.land import hazards

    src = inspect.getsource(hazards._sync_air_quality_readings)

    # ⛔ Anchor on the statement that WRITES POLLUTANTS, not on "the first
    # UPDATE air_quality_stations". The function contains a second one — the
    # per-station queue stamp — and it is written first. Splitting on the bare
    # table name pointed this test at the stamp on 2026-09-09 and turned it red
    # against production code that was entirely correct.
    updates = [seg for seg in src.split("UPDATE air_quality_stations")[1:]
               if "SET pm25" in seg.split('"""')[0]]
    assert len(updates) == 1, (
        f"expected exactly one pollutant UPDATE, found {len(updates)}. If the "
        "write was split across statements this test now covers only part of it."
    )
    update_call = updates[0]
    for param in ("pm25", "so2", "no2", "o3", "co", "pm10",
                  "bc", "no", "nox", "co2", "pm1", "pm4", "ch4", "ufp"):
        assert f'_concentration_or_none(values.get("{param}"))' in update_call, (
            f"pollutant {param!r} reaches the UPDATE without the concentration guard"
        )


@pytest.mark.parametrize("fill_value", [-9999, -999, -1111, -995, -9, -0.01, -50])
def test_concentration_or_none_rejects_fill_values_and_negatives(fill_value):
    """A concentration can never be negative — this is a domain constraint, not
    a blocklist of the sentinels OpenAQ happens to have shipped so far."""
    assert _concentration_or_none(fill_value) is None


def test_concentration_or_none_keeps_temperature_style_negative_readings_away():
    """_score_or_none must still pass a genuine negative reading (e.g. -55°C)
    through unchanged. This guards against someone later 'simplifying' the two
    helpers into one and silently deleting real cold-weather data."""
    assert _score_or_none(-55) == -55.0
    assert _concentration_or_none(-55) is None


def test_argo_read_paths_exclude_bad_quality_oxygen():
    """Argo QC 3, 4 and 9 mean probably-bad, bad and missing. A reading the
    source flagged as bad must not be served as a measurement."""
    import inspect
    from backend.domains import sensors

    src = inspect.getsource(sensors)
    for sql_name in ("_ARGO_FLOAT_SQL", "_ARGO_TRAIL_SQL"):
        assert sql_name in src, f"{sql_name} not found"
    # Both queries must null out oxygen and ph when the source flagged them bad.
    assert src.count("oxygen_qc NOT IN (3, 4, 9)") >= 2, (
        "at least one Argo read path serves oxygen without checking its QC flag"
    )
    assert src.count("ph_qc NOT IN (3, 4, 9)") >= 2, (
        "at least one Argo read path serves pH without checking its QC flag"
    )


def test_sio_bic_does_not_invent_a_depth_unit():
    """An empty source cell means the source declared no unit. Supplying 'm'
    ourselves makes an assumption indistinguishable from a declaration."""
    import inspect
    from backend.ingestion import sio_bic_ingest

    src = inspect.getsource(sio_bic_ingest)
    assert 'row.get("Depth Unit") or "m"' not in src, (
        "the depth_unit fallback still supplies a unit the source did not give"
    )
    assert 'row.get("Depth Unit")' in src, "depth_unit is no longer captured at all"


def test_noise_sources_never_share_a_normalised_column():
    """Pulse-block days (ICES) and sound pressure level (EMODnet) are not
    commensurable. Normalising each to 0-1 into one column hides that."""
    import inspect
    from backend.ingestion import noise_ingest

    src = inspect.getsource(noise_ingest)
    assert "noise_norm" not in src, (
        "noise_norm still exists; PBD and SPL are still blended into one column"
    )
    assert "pbd_norm" in src and "spl_norm" in src, (
        "the two sources must normalise into separate columns"
    )
    # The magic constants must be named, not inline.
    assert "PBD_DAYS_PER_YEAR" in src, "the 180.0 divisor is still a magic number"
    assert "SPL_REF_DB" in src, "the 80.0 reference level is still a magic number"


def test_coral_columns_do_not_assert_a_unit_the_source_never_gave():
    """DSCRTP exposes 37 fields and none is a unit. Verified 2026-09-04 against
    the live FeatureServer. A column name claiming ml/L, PSU or degrees C is
    this platform's assertion, not the source's."""
    import inspect
    from backend.schema import biodiversity

    # There is no module-level BIODIVERSITY_DDL constant — the DDL is an inline
    # string literal inside ensure_noaa_corals(). Isolate its CREATE TABLE
    # column list directly from that function's source.
    src = inspect.getsource(biodiversity.ensure_noaa_corals)
    coral = src.split("CREATE TABLE IF NOT EXISTS noaa_corals_records")[1].split(")")[0]
    for banned in ("oxygen_ml_l", "salinity_psu", "temperature_c"):
        assert banned not in coral, f"{banned} still asserts a unit DSCRTP does not supply"
    for expected in ("oxygen", "salinity", "temperature"):
        assert expected in coral, f"{expected} column is missing"


def test_every_offshore_activities_query_filters_activity_type():
    """The table is deliberately multi-type. Two external analyses have already
    attributed a methane measurement to an offshore wind lease by not filtering.

    A plain "activity_type appears somewhere after FROM" scan over-reports and
    under-reports at once: it can walk past the query's own closing quote into
    unrelated code below (false pass — see the feature-bboxes note), and it is
    blind to `activity_type` sitting in the SELECT list *before* FROM (false
    fail — the MVT/raster tile queries). This version bounds each query to its
    own string literal and then applies a short, individually-justified list
    of exemptions for the query shapes that do not carry the attribution risk
    the rule exists for. Every exemption below was inspected by hand against
    the live source on 2026-09-04; none is a blanket allowance.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]

    def _sql_tail(text: str, end: int, limit: int = 400) -> str:
        """Text following `end`, truncated at the enclosing string literal's
        own closing quote so a short clause in the *next* statement can never
        be mistaken for part of this query."""
        window = text[end : end + limit]
        candidates = []
        for closer in ('"""', "'''"):
            idx = window.find(closer)
            if idx != -1:
                candidates.append(idx)
        for i, ch in enumerate(window):
            if ch in ('"', "'") and (i == 0 or window[i - 1] != "\\"):
                candidates.append(i)
                break
        if candidates:
            return window[: min(candidates)]
        return window

    offenders = []
    for path in root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")

        if path.name == "spatial_v2.py":
            # offshore_at() and offshore_by_id() build their SELECT list from
            # this f-string constant rather than inline. Confirm it still
            # carries activity_type independently of the queries below —
            # if it is ever edited to drop the column, this catches that
            # directly instead of relying on the exemption staying accurate.
            const = re.search(r'_OFFSHORE_PANEL_COLUMNS\s*=\s*"""(.*?)"""', text, re.S)
            assert const and "activity_type" in const.group(1), (
                "_OFFSHORE_PANEL_COLUMNS no longer carries activity_type — "
                "offshore_at/offshore_by_id would stop exposing the real "
                "per-row type, and the exemption for them below would be wrong"
            )

        for match in re.finditer(r"FROM\s+offshore_activities", text, re.I):
            line = text[: match.start()].count("\n") + 1
            tail = _sql_tail(text, match.end())
            before = text[max(0, match.start() - 300) : match.start()]

            if "activity_type" in tail:
                continue  # a real WHERE/GROUP BY filter on the type

            if "activity_type" in before or "_OFFSHORE_PANEL_COLUMNS" in before:
                # activity_type (or the column-list constant just verified
                # above) is already in THIS query's SELECT list — the real
                # per-row type reaches the caller, so nothing is conflated.
                # Covers the 4 MVT/zone tile queries, the raster tile query,
                # and offshore_at / offshore_by_id.
                continue

            if not tail.strip():
                # A bare `SELECT count(*) FROM offshore_activities` with no
                # WHERE/GROUP BY at all — internal sync-log bookkeeping
                # ("N new / N total" in domains/offshore.py) or the admin
                # layer-registry row count (layer_ops.py). An honest
                # whole-table total, never presented as a per-type figure.
                continue

            if "_collect_tiles" in text[max(0, match.start() - 450) : match.start()]:
                # offshore_tile_baker.py: scans bbox extents across ALL
                # activity types to pick which tiles need (re)baking for the
                # multi-type raster pyramid. Not a count or an attribution.
                continue

            if "offshore_activities_feature_bboxes" in text[max(0, match.start() - 1500) : match.start()]:
                # /offshore-activities/feature-bboxes returns id + bbox only
                # (no activity_type, no count) for camera fly-to cycling. It
                # already supports an explicit optional `types` filter for
                # callers that want to narrow it, and is unfiltered by design
                # otherwise — consistent with the tile endpoints it feeds.
                continue

            offenders.append(f"{path.relative_to(root)}:{line}")

    assert not offenders, "queries missing an activity_type filter: " + ", ".join(offenders)
