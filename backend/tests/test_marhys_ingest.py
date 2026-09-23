# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""MARHYS 4.0 parser — asserted against a real slice of the published workbook.

The fixture is 24 verbatim rows lifted out of `MARHYS_DB_4_0.xlsx`, chosen to
carry every awkward case the full file contains: all four sample types, the
transposed Guaymas coordinates, the sign-flipped Saldanha longitude, rows with
no position, rows with a latitude but no longitude, rows the source never named,
and end-member samples whose magnesium is a real zero.

⭐ The fixture ships in the repository because MARHYS is CC-BY-4.0 — unlike the
MEMENTO fixture next door, which is licence-restricted and excluded.
"""

import pathlib

import pytest

from backend.ingestion.marhys_ingest import (
    MarhysFormatError,
    _NUMERIC_COLUMNS,
    parse_marhys,
)

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "marhys" / "marhys_slice.xlsx"


@pytest.fixture(scope="module")
def parsed():
    return parse_marhys(FIXTURE.read_bytes())


@pytest.fixture(scope="module")
def records(parsed):
    return parsed["records"]


def _by_id(records, sample_id):
    hits = [r for r in records if r["sample_id"] == sample_id]
    assert hits, f"fixture no longer contains {sample_id!r}"
    return hits[0]


# ── row inclusion ───────────────────────────────────────────────────────────

def test_every_source_row_becomes_a_record(records):
    """24 rows in, 24 records out.

    ⛔ Regression guard. An earlier draft decided inclusion on the CLEANED
    Sample-ID, so every row the source labels "not given" was skipped — 71 real
    samples on the full file, and the total came out 6717 instead of 6788. A
    sample the source did not name is still a sample.
    """
    assert len(records) == 24


def test_unnamed_samples_survive_with_a_null_id(records):
    unnamed = [r for r in records if r["sample_id"] is None]
    assert len(unnamed) == 3, "the fixture carries three rows the source did not name"
    # They are real samples, not empty rows.
    assert all(r["lat"] is not None for r in unnamed)


def test_source_row_is_unique_and_positional(records):
    """The key is the row's position, because Sample-ID is not unique.

    On the full file 6788 rows carry only 6108 distinct Sample-IDs. Keying an
    upsert on the label would collapse 680 distinct samples into each other —
    the same defect that produced 1,584 duplicate tailings rows in production.
    """
    positions = [r["source_row"] for r in records]
    assert len(set(positions)) == len(positions)
    assert positions == sorted(positions)
    assert positions[0] == 1


# ── coordinates ─────────────────────────────────────────────────────────────

def test_transposed_guaymas_rows_keep_their_numbers_and_get_no_geometry(records):
    """The source's own error is preserved, not repaired and not hidden."""
    guaymas = [r for r in records if r["coord_status"] == "out_of_range"]
    assert len(guaymas) == 3

    for row in guaymas:
        assert row["lat"] > 90, "the impossible latitude must reach the database"
        assert "Guaymas" in (row["vent_area"] or "")
        # ⛔ Not transposed back. Guaymas Basin is at 27.01 N / -111.40 W, and it
        # is obvious what happened — but repairing it here would make the
        # platform uncheckable against its source.
        assert row["lon"] == pytest.approx(27.0, abs=0.1)


def test_rows_without_a_position_are_kept_and_labelled(records):
    missing = [r for r in records if r["coord_status"] == "missing"]
    assert len(missing) == 8
    assert all(r["lat"] is None or r["lon"] is None for r in missing)
    # A latitude with no longitude still cannot be placed.
    half = [r for r in missing if r["lat"] is not None and r["lon"] is None]
    assert len(half) == 2


def test_placeable_rows_are_the_remainder(records):
    ok = [r for r in records if r["coord_status"] == "ok"]
    assert len(ok) == 13
    assert all(abs(r["lat"]) <= 90 and abs(r["lon"]) <= 180 for r in ok)


def test_saldanha_longitude_is_passed_through_wrong(records):
    """MARHYS puts Saldanha in Turkey. We render it in Turkey.

    InterRidge has 36.5667 / -33.4333; MARHYS ships 36.5667 / +33.6, which GEBCO
    2020 places 417 m above sea level. It is the only one of 811 MARHYS
    positions that lands on dry ground.
    """
    saldanha = [r for r in records if (r["vent_area"] or "").startswith("Saldanha")]
    assert saldanha, "fixture no longer carries Saldanha"
    for row in saldanha:
        assert row["lon"] == pytest.approx(33.6, abs=0.01)
        assert row["coord_status"] == "ok"   # numerically valid, factually wrong


# ── values ──────────────────────────────────────────────────────────────────

def test_zero_magnesium_is_a_value_not_a_gap(records):
    """⛔ The single most destructive "hygiene" rule available on this dataset.

    An end-member composition is defined by extrapolation to zero magnesium. On
    the full file 1252 of the 1265 magnesium zeros sit on `EM` samples, which
    carry only 24 non-zero magnesium values between them. Coercing 0 to NULL
    would erase the defining property of those samples.
    """
    zeros = [r for r in records if r["mg_mmol_kg"] == 0]
    assert len(zeros) == 8
    assert all(r["mg_mmol_kg"] is not None for r in zeros)
    assert {r["sample_type"] for r in zeros} == {"EM"}


def test_placeholders_become_null_never_empty_string(records):
    for row in records:
        for field in ("sample_id", "vent_id", "vent_site", "vent_area",
                      "sampler_type", "region_large"):
            assert row[field] != "", f"{field} came back as an empty string"
            assert (row[field] or "").lower() not in {"not given", "not applicable"}


def test_date_is_carried_through_verbatim(records):
    """The source's date column is free text in eight formats. It is not parsed.

    Michal's instruction, 2026-09-22: show the acquisition date exactly as the
    source writes it. A year-only entry stays "1977"; a range stays a range.
    """
    dates = [r["date_raw"] for r in records if r["date_raw"]]
    assert "1977" in dates
    assert any(" - " in d for d in dates), "the fixture carries a date range"
    assert all(isinstance(d, str) for d in dates)


def test_sample_types_are_all_four(records):
    types = {r["sample_type"] for r in records}
    assert types == {"HF", "EM", "SW", "STD"}


# ── params and units ────────────────────────────────────────────────────────

def test_long_tail_lands_in_params_with_a_unit_for_every_key(parsed, records):
    units = parsed["param_units"]
    assert len(units) > 100, "the sparse tail is ~149 columns"

    seen = set()
    for row in records:
        assert isinstance(row["params"], dict)
        seen |= set(row["params"])
    assert seen, "no row carried a single long-tail parameter"
    missing = sorted(seen - set(units))
    assert not missing, f"params keys with no declared unit: {missing}"


def test_named_columns_never_leak_into_params(records):
    named = {field for field, _unit in _NUMERIC_COLUMNS.values()}
    for row in records:
        assert not (set(row["params"]) & named)


def test_params_hold_no_nulls(records):
    """A missing sample is absent from params, never stored as 0 or None."""
    for row in records:
        assert all(v is not None for v in row["params"].values())


# ── layout guard ────────────────────────────────────────────────────────────

def test_a_reshuffled_workbook_is_refused(tmp_path):
    """⛔ A republished file must break this parser, not silently repopulate it.

    Every value in a column-shifted workbook is still a plausible number — just
    attributed to the wrong element. Failing loudly is the only safe outcome.
    """
    import openpyxl

    book = openpyxl.load_workbook(FIXTURE)
    sheet = book["Tabelle1"]
    sheet.cell(row=12, column=65).value = "Ca"      # Mg's column, relabelled
    broken = tmp_path / "reshuffled.xlsx"
    book.save(broken)

    with pytest.raises(MarhysFormatError, match="Mg"):
        parse_marhys(broken.read_bytes())


def test_a_changed_unit_is_refused(tmp_path):
    """Storing µmol/kg values in a column named mmol/kg is a 1000× error."""
    import openpyxl

    book = openpyxl.load_workbook(FIXTURE)
    book["Tabelle1"].cell(row=13, column=58).value = "mmol/kg"   # Fe, really µmol/kg
    broken = tmp_path / "rescaled.xlsx"
    book.save(broken)

    with pytest.raises(MarhysFormatError, match="fe_umol_kg"):
        parse_marhys(broken.read_bytes())
