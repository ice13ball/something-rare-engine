# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""What ISA's Darwin Core archives publish, against what we keep.

Measured 2026-09-15 across all 140 archives on datasets.obis.org:

* `occurrence.txt` publishes **52 columns**; the ingest kept 15 and said
  nothing about the other 37. Not a fetch gap — we download the whole zip —
  but a retention choice nobody had written down, which is the same thing as
  no choice at all once the person who made it has gone.
* `extendedmeasurementorfact.txt` ships in every archive and had **never been
  opened**. 42 archives hold real rows (1.7 MB in total, every sampled row of
  a single type, "Relative abundance"); the other 98 hold a header and
  nothing else. That difference could not have been stated before, because
  nobody had read the file.

And one real silent failure, which is why this file exists at all:
`row.get(k)` answers `None` both for a column ISA stopped publishing and for
a row that happens to be blank. If `decimalLatitude` were renamed, every
occurrence would be skipped for want of coordinates and the archive would
parse to **zero stations, successfully**.
"""
import io
import logging
import zipfile

import pytest

from ingestion import deepdata_dwc_ingest as mod

_KEPT = set(mod._OCC_FIELDS)
_REFUSED = set(mod._OCC_FIELDS_UNUSED)


def _occurrence_bytes(columns, rows=1) -> bytes:
    header = "\t".join(columns)
    line = "\t".join("1.0" for _ in columns)
    return ("\n".join([header] + [line] * rows)).encode()


# ─────────────────────────────────────────────────────────────────────────────
# A column that disappears must not read as a column that is blank.
# ─────────────────────────────────────────────────────────────────────────────

def test_a_renamed_required_column_is_loud():
    cols = [c for c in mod.OCC_COLUMNS_SEEN if c != "decimalLatitude"]
    cols.append("latitude")          # ISA renames it; everything else is fine

    with pytest.raises(mod.MissingOccurrenceColumns) as exc:
        list(mod._iter_occurrences(_occurrence_bytes(cols), "some_slug"))

    msg = str(exc.value)
    assert "decimalLatitude" in msg, f"the error does not name the column: {msg}"
    assert "some_slug" in msg, f"the error does not name the archive: {msg}"


def test_the_failure_it_replaces_produced_zero_rows_and_no_error():
    """⛔ The point of the guard, shown rather than asserted about.

    Reading the same header with a plain `row.get` — what the ingest did
    before — yields a full set of occurrences whose coordinates are all None.
    `aggregate_stations` skips exactly those, so the archive parses clean and
    empty.
    """
    cols = [c for c in mod.OCC_COLUMNS_SEEN if c != "decimalLatitude"]
    rows = [{k: r.get(k) for k in mod._OCC_FIELDS} for r in
            __import__("csv").DictReader(
                io.StringIO(_occurrence_bytes(cols, rows=3).decode()), delimiter="\t")]

    assert len(rows) == 3, "the fixture itself is wrong"
    assert all(r["decimalLatitude"] is None for r in rows), (
        "the fixture no longer reproduces the silent failure")
    stations = mod.aggregate_stations("some_slug", {"slug": "some_slug"}, rows)
    assert stations == [], (
        "three unusable occurrences produced stations — then the guard above "
        "is protecting against the wrong thing")


def test_a_complete_header_parses():
    """Positive control: without it the guard could reject everything."""
    rows = list(mod._iter_occurrences(_occurrence_bytes(list(mod.OCC_COLUMNS_SEEN), 2), "s"))
    assert len(rows) == 2
    assert set(rows[0]) == _KEPT, "the parser stopped yielding the fields we keep"


def test_an_optional_column_may_be_absent_but_says_so(caplog):
    """Archives legitimately vary — tolerated, not silent."""
    cols = [c for c in mod.OCC_COLUMNS_SEEN if c != "samplingProtocol"]
    with caplog.at_level(logging.INFO):
        rows = list(mod._iter_occurrences(_occurrence_bytes(cols), "s"))

    assert len(rows) == 1, "an optional column's absence stopped the parse"
    assert rows[0]["samplingProtocol"] is None
    assert any("samplingProtocol" in r.getMessage() for r in caplog.records), (
        "an omitted column left no trace at all")


# ─────────────────────────────────────────────────────────────────────────────
# Every published column is kept or refused — with a reason somebody checked.
# ─────────────────────────────────────────────────────────────────────────────

def test_every_published_column_is_kept_or_refused():
    unclassified = [c for c in mod.OCC_COLUMNS_SEEN
                    if c not in _KEPT and c not in _REFUSED]
    assert unclassified == [], (
        f"{len(unclassified)} of ISA's columns are neither kept nor refused: "
        f"{unclassified}. An unlisted column is indistinguishable from one "
        "nobody read the header for.")


def test_no_column_is_both_kept_and_refused():
    both = sorted(_KEPT & _REFUSED)
    assert both == [], (
        f"{both} are both kept and listed as refused. The reason text is the "
        "half a reader would believe.")


def test_every_refusal_carries_a_reason():
    """⛔ A false reason is worse than no reason; an empty one is worse still."""
    thin = {c: r for c, r in mod._OCC_FIELDS_UNUSED.items()
            if len((r or "").strip()) < 15}
    assert thin == {}, f"these refusals say nothing checkable: {thin}"


def test_we_do_not_claim_to_keep_a_column_isa_never_publishes():
    """⭐ The inverse gap: a field we ask for that does not exist reads as
    None for every row, forever, exactly like a blank value."""
    phantom = sorted(_KEPT - set(mod.OCC_COLUMNS_SEEN))
    assert phantom == [], (
        f"we read {phantom}, which ISA's header does not contain. Each one is "
        "a column of None that no error will ever mention.")


def test_the_required_set_is_the_set_the_station_build_actually_needs():
    """The floor: dropping a name from _OCC_FIELDS_REQUIRED must be a choice,
    not a slip. These six are what `aggregate_stations` reads to place and
    identify a station."""
    assert mod._OCC_FIELDS_REQUIRED <= _KEPT, (
        "a column is required but not even read")
    for name in ("decimalLatitude", "decimalLongitude", "eventID", "scientificName"):
        assert name in mod._OCC_FIELDS_REQUIRED, (
            f"{name} is optional; without it every station loses its position "
            "or its identity, and the archive parses to a clean zero")


# ─────────────────────────────────────────────────────────────────────────────
# The measurement file we had never opened.
# ─────────────────────────────────────────────────────────────────────────────

_EMOF_HEADER = "id\tdataset_id\tmeasurementID\tmeasurementType\tmeasurementValue\tmeasurementUnit"


def _zip_with(emof: str | None) -> tuple[zipfile.ZipFile, set[str]]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        if emof is not None:
            zf.writestr(mod._EMOF_NAME, emof)
        zf.writestr("eml.xml", "<eml/>")
    zf = zipfile.ZipFile(buf)
    return zf, set(zf.namelist())


def test_measurements_are_read_and_inventoried():
    body = "\n".join([
        _EMOF_HEADER,
        "1\td\tm1\tRelative abundance\t0.5\t%",
        "2\td\tm2\tRelative abundance\t0.25\t%",
        "3\td\tm3\tWet weight biomass\t12\tg",
    ])
    zf, names = _zip_with(body)
    count, types = mod._read_measurements(zf, names, "s")

    assert count == 3, f"counted {count} measurement rows, expected 3"
    assert types == ["Relative abundance", "Wet weight biomass"], (
        f"distinct types wrong: {types}")


def test_a_header_only_file_is_zero_measured_not_unreadable():
    """98 of 140 archives look exactly like this. Zero is the answer, and it
    is an answer — not an error and not an absence."""
    zf, names = _zip_with(_EMOF_HEADER)
    assert mod._read_measurements(zf, names, "s") == (0, [])


def test_an_absent_file_is_also_zero_but_reaches_a_different_branch(caplog):
    zf, names = _zip_with(None)
    with caplog.at_level(logging.INFO):
        assert mod._read_measurements(zf, names, "s") == (0, [])
    assert any(mod._EMOF_NAME in r.getMessage() for r in caplog.records), (
        "an archive missing the file entirely left no trace")


def test_a_measurement_file_we_cannot_interpret_raises():
    """⛔ Counting rows whose meaning we cannot read would be a number that
    means nothing — and it would look exactly like a real count."""
    zf, names = _zip_with("id\tdataset_id\tvalue\n1\td\t7")
    with pytest.raises(ValueError, match="measurementType"):
        mod._read_measurements(zf, names, "s")


def test_the_measurement_columns_reach_the_database():
    """⛔ Guard the call site. The archive INSERT is built from a column list;
    a field added to the parsed dict but not to that list is written nowhere,
    silently and forever."""
    import inspect

    from domains import biodiversity

    src = inspect.getsource(biodiversity.upsert_dwc_archive_and_stations)
    for col in ("measurement_count", "measurement_types"):
        assert f'"{col}"' in src, (
            f"{col} is parsed out of every archive and never written — the "
            "INSERT column list does not mention it")
