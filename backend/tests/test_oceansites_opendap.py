# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""OPeNDAP reading of OceanSITES GDAC files — parsers, planning, decoding.

Every .dds/.das/.ascii below was recorded from the real server on 2026-10-01
(``fixtures/oceansites_gdac/opendap/``): a TAO per-variable D file with a DEPTH
axis, a PAP CTD file, a plain-array LOCO-IRMINGSEA SBE37 (no Grid, no QC), an
MBARI R-only file (5-token name, 4-D grid, float QC), a TAO SST file whose last
third is fill, and the files that taught us a trap (PAPA's per-variable DEPTH_*
axes, K276's wrong ``ancillary_variables``, BATS bottle profiles).
``index_T0N140W.txt`` is the verbatim index lines of one real directory.

⛔ What is protected: a value stored is a value the instrument reported — fill
becomes NULL (never data), QC rides beside it, units are the file's own, nothing
is averaged, and a server that cannot answer is not a file with no data.
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from ingestion import oceansites_history as idx
from ingestion import oceansites_opendap as od
from oceansites_fixture_server import (
    BATS_BTL, FIX, IRMINGSEA, K276, MBARI, PAP2, PAPA, T0N140W, T8S165E,
    FixtureServer, read,
)

W = od.HISTORY_STANDARD_NAMES


def _stem(f):
    return Path(f).stem


def _dds_das(f):
    stem = _stem(f)
    return (od.parse_dds(read(stem, "dds").decode("latin-1")),
            od.parse_das(read(stem, "das").decode("latin-1")))


async def _fetch(f, server=None, wanted=W):
    server = server or FixtureServer()
    async with httpx.AsyncClient(transport=server.transport()) as c:
        return await od.fetch_file_series(c, f, wanted), server


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(od, "REQUEST_DELAY", 0)
    monkeypatch.setattr(od, "_RETRY_DELAY", 0)


# ── .dds ────────────────────────────────────────────────────────────────────


def test_dds_grid_with_depth_axis():
    dds, _ = _dds_das(T0N140W)
    assert dds["TEMP"].grid and dds["TEMP"].dims == (("TIME", 27005), ("DEPTH", 15))
    assert dds["TEMP_QC"].dims == (("TIME", 27005), ("DEPTH", 15))
    assert not dds["TIME"].grid and dds["TIME"].dims == (("TIME", 27005),)
    assert dds["TEMP_DM"].dtype == "String"


def test_dds_plain_array_is_not_a_grid():
    dds, _ = _dds_das(IRMINGSEA)
    assert not dds["TEMP"].grid and dds["TEMP"].dims == (("TIME", 143267),)
    assert dds["DEPTH"].dims == (("DEPTH", 1),)
    assert "TEMP_QC" not in dds


def test_dds_four_dimensional_grid_keeps_all_axes():
    dds, _ = _dds_das(MBARI)
    assert dds["TEMP"].dims == (("TIME", 2993), ("DEPTH", 5), ("LATITUDE", 1), ("LONGITUDE", 1))
    assert "DEPTH_bnds" in dds and dds["DEPTH_bnds"].dims[1] == ("bnds", 2)


def test_dds_per_variable_depth_axes():
    dds, _ = _dds_das(PAPA)
    assert dds["TEMP"].dims[:2] == (("TIME", 9829), ("DEPTH_TEMP", 17))
    assert dds["PSAL"].dims[1][0] == "DEPTH_PSAL"


# ── .das ────────────────────────────────────────────────────────────────────


def test_das_variable_attributes_pass_through_as_declared():
    _, das = _dds_das(T0N140W)
    t = das["TEMP"]
    assert t["standard_name"] == "sea_water_temperature"
    assert t["units"] == "degree_Celsius"
    assert t["_FillValue"] == [-999.0]
    assert das["TEMP_QC"]["_FillValue"] == [-1.0]
    assert das["TIME"]["units"] == "days since 1950-01-01T00:00:00Z"


def test_das_globals_and_citation_survive_quoted_semicolons_and_newlines():
    _, das = _dds_das(MBARI)
    g = das["NC_GLOBAL"]
    assert g["citation"] == ("These data were collected and made freely available by the "
                             "Monterey Bay Aquarium Research Institute.")
    assert g["wmo_platform_code"] == "46091" and g["site_code"] == "MBARI"
    # the very next variable is still read: a ';' inside a string did not end the block
    assert das["TEMP"]["_FillValue"] == [-1.0e34] and das["TEMP"]["units"] == "celsius"
    # PSAL declares units " " (a blank): it is stored as "no unit", not guessed ("psu"/"1")
    assert das["PSAL"]["units"] == " "


def test_das_nested_dods_container_is_skipped_not_mistaken_for_a_variable():
    _, das = _dds_das(T0N140W)
    assert "DODS" not in das and "TEMP_DM" in das
    assert das["NC_GLOBAL"]["platform_code"] == "T0N140W"


# ── time ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("units", [
    "days since 1950-01-01T00:00:00Z",   # 119 of 120 files sampled from the live GDAC
    "days since 1950-01-01 00:00:00",    # the 120th
])
def test_time_units_seen_on_the_live_server(units):
    origin, sec = od.parse_time_units(units)
    assert origin == datetime(1950, 1, 1, tzinfo=timezone.utc) and sec == 86400.0


def test_time_units_are_read_not_assumed():
    origin, sec = od.parse_time_units("hours since 2000-01-01 12:00:00 +02:00")
    assert origin == datetime(2000, 1, 1, 10, tzinfo=timezone.utc) and sec == 3600.0
    assert od.decode_time(2, origin, sec) == datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
    with pytest.raises(od.UnsupportedFile):
        od.parse_time_units("months since 1950-01-01")
    with pytest.raises(od.UnsupportedFile):
        od.parse_time_units("days since 1950-01-01", calendar="360_day")


# ── planning ────────────────────────────────────────────────────────────────


def test_plan_stride_and_depth_levels_for_a_tao_file():
    dds, das = _dds_das(T0N140W)
    plan = od.plan_file(dds, das, W)
    (p,) = plan.vars
    assert (p.name, p.qc_name, p.std_name) == ("TEMP", "TEMP_QC", "sea_water_temperature")
    assert p.n_time == 27005 and p.stride == 181 and 27005 / 181 <= 150 < 27005 / 180
    assert p.depth_step == 2 and p.depth_indices == [0, 2, 4, 6, 8, 10, 12, 14]   # <= 10 levels
    assert od.build_constraint(plan, dds) == (
        "TIME[0:181:27004],DEPTH[0:2:14],TEMP.TEMP[0:181:27004][0:2:14],TEMP_QC.TEMP_QC[0:181:27004][0:2:14]")


def test_plain_array_is_addressed_without_the_grid_prefix_and_has_no_qc():
    dds, das = _dds_das(IRMINGSEA)
    plan = od.plan_file(dds, das, W)
    assert [(p.name, p.qc_name) for p in plan.vars] == [("TEMP", None), ("PSAL", None)]
    q = od.build_constraint(plan, dds)
    assert q == "TIME[0:956:143266],DEPTH,TEMP[0:956:143266],PSAL[0:956:143266]"
    assert ".TEMP" not in q                      # TEMP.TEMP[...] is a 400 on a plain array


def test_four_dim_grid_pins_the_size_one_axes():
    dds, das = _dds_das(MBARI)
    q = od.build_constraint(od.plan_file(dds, das, W), dds)
    assert "TEMP.TEMP[0:20:2992][0:1:4][0:1:0][0:1:0]" in q


def test_per_variable_depth_axis_is_a_depth_axis():
    dds, das = _dds_das(PAPA)
    plan = od.plan_file(dds, das, W)
    names = {p.name: p for p in plan.vars}
    assert names["TEMP"].depth_axis == 1 and names["TEMP"].depth_indices == list(range(0, 17, 2))
    q = od.build_constraint(plan, dds)
    assert "DEPTH_TEMP[0:2:16]" in q and "DEPTH_PSAL[0:2:13]" in q


def test_a_variable_with_a_range_bin_axis_is_skipped_with_a_reason():
    dds, das = _dds_das(K276)   # UCUR/VCUR here are fine; use a wanted set that excludes them
    plan = od.plan_file(dds, das, {"sea_water_temperature"})
    assert [p.name for p in plan.vars] == ["TEMP"]
    assert od.is_depth_dim("DEPTH") and od.is_depth_dim("DEPTH_TEMP")
    assert not od.is_depth_dim("BINDEPTH") and not od.is_depth_dim("CELL")


def test_wrong_ancillary_variables_does_not_hand_one_variable_anothers_qc():
    """Real K276: VCUR says ancillary_variables "UCUR_QC". Trusting it graded the
    northward velocity with the eastward flags and, worse, put UCUR_QC in the
    constraint twice, which the server answers with a 400."""
    dds, das = _dds_das(K276)
    assert "UCUR_QC" in str(das["VCUR"].get("ancillary_variables"))
    plan = od.plan_file(dds, das, W)
    assert {p.name: p.qc_name for p in plan.vars}["VCUR"] == "VCUR_QC"
    items = od.build_constraint(plan, dds).split(",")
    assert len(items) == len(set(items))


def _packed_das(f, variable, *attrs):
    """A copy of the REAL .das of ``f`` with extra attribute lines added to one variable.

    ⚠️ Synthetic on purpose: none of the recorded GDAC files is packed, so the packed case
    is a real .das with ``scale_factor`` / ``add_offset`` inserted. The parser sees the
    real structure; only these attribute lines are invented."""
    text = read(_stem(f), "das").decode("latin-1")
    head = f"    {variable} {{\n"
    assert text.count(head) == 1
    extra = "".join(f"        Float32 {k} {v};\n" for k, v in attrs)
    return text.replace(head, head + extra)


def test_a_packed_variable_is_left_out_not_stored_unscaled():
    dds, _ = _dds_das(PAP2)
    das = od.parse_das(_packed_das(PAP2, "TEMP", ("scale_factor", 0.001), ("add_offset", 20.0)))
    plan = od.plan_file(dds, das, W)
    assert [p.name for p in plan.vars] == ["PSAL"]
    assert ("TEMP", od.PACKED_REASON) in plan.skipped


@pytest.mark.parametrize("attrs", [
    [("scale_factor", 0.01)],
    [("add_offset", 273.15)],
    [("scale_factor", 1.0), ("add_offset", 5.0)],
])
def test_either_packing_attribute_alone_is_enough(attrs):
    dds, _ = _dds_das(PAP2)
    das = od.parse_das(_packed_das(PAP2, "TEMP", *attrs))
    assert [p.name for p in od.plan_file(dds, das, W).vars] == ["PSAL"]


def test_identity_packing_changes_no_value_so_the_variable_is_kept():
    dds, _ = _dds_das(PAP2)
    das = od.parse_das(_packed_das(PAP2, "TEMP", ("scale_factor", 1.0), ("add_offset", 0.0)))
    assert {p.name for p in od.plan_file(dds, das, W).vars} == {"TEMP", "PSAL"}


def test_a_file_whose_every_wanted_variable_is_packed_is_unsupported_and_says_which():
    dds, _ = _dds_das(PAP2)
    text = _packed_das(PAP2, "TEMP", ("scale_factor", 0.01))
    text = text.replace("    PSAL {\n", "    PSAL {\n        Float32 add_offset 30.0;\n")
    with pytest.raises(od.UnsupportedFile) as e:
        od.plan_file(dds, od.parse_das(text), W)
    assert sorted(e.value.packed) == ["PSAL", "TEMP"] and od.PACKED_REASON in str(e.value)


async def test_fetching_a_file_with_a_packed_variable_reads_only_the_others():
    das_text = _packed_das(PAP2, "TEMP", ("scale_factor", 0.001), ("add_offset", 20.0))
    good = FixtureServer()

    def handler(request):
        if request.url.path.endswith(".das") and "PAP-2" in request.url.path:
            return httpx.Response(200, content=das_text.encode("latin-1"))
        return good.handle(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        res = await od.fetch_file_series(c, PAP2, W)
    assert {r.variable for r in res.series} == {"PSAL"}
    assert res.variables_read == {"PSAL"}
    assert [v for v, why in res.skipped if why == od.PACKED_REASON] == ["TEMP"]


def test_bottle_profile_file_is_unsupported_not_empty():
    dds, das = _dds_das(BATS_BTL)
    with pytest.raises(od.UnsupportedFile):
        od.plan_file(dds, das, W)


# ── decoding real responses ─────────────────────────────────────────────────


async def test_tao_grid_file_end_to_end_with_real_bytes():
    res, server = await _fetch(T0N140W)
    assert res.requests == 3 and len(server.requests) == 3
    assert [r[1].rsplit(".", 1)[-1] for r in server.requests] == ["dds", "das", "ascii"]
    assert len(res.series) == 8
    assert [s.depth_index for s in res.series] == [0, 2, 4, 6, 8, 10, 12, 14]
    assert [s.depth_m for s in res.series] == [1.0, 10.0, 25.0, 45.0, 80.0, 120.0, 180.0, 500.0]
    s0 = res.series[0]
    assert (s0.variable, s0.units, s0.standard_name) == ("TEMP", "degree_Celsius", "sea_water_temperature")
    assert (s0.n_total, s0.stride, len(s0.times), len(s0.vals), len(s0.qc)) == (27005, 181, 150, 150, 150)
    # the first sample is TIME[0] = 23634.159722... days since 1950 (read from the response)
    assert s0.times[0] == datetime(1950, 1, 1, tzinfo=timezone.utc) + timedelta(days=23634.159722222223)
    assert s0.times == sorted(s0.times)


async def test_declared_fill_and_the_unreal_1e33_become_null_with_their_flags_kept():
    res, _ = await _fetch(T0N140W)
    raw = read(_stem(T0N140W), "ascii").decode()
    assert "-999.0" in raw and "1.0E33" in raw
    deepest = res.series[-1]                                  # 500 m: almost all 1.0E33 on the wire
    assert sum(v is None for v in deepest.vals) == 148
    for s in res.series:
        assert all(v is None or (-5 < v < 40) for v in s.vals), "a fill leaked into the data"
        assert -999.0 not in s.vals and 1.0e33 not in s.vals
        # every NULL value still carries the producer's flag (9 missing, 3 / 4 bad)
        for v, q in zip(s.vals, s.qc):
            if v is None:
                assert q in (3, 4, 9)
    assert res.fills_nulled == 212
    assert {q for s in res.series for q in s.qc} <= {1, 3, 4, 9}
    assert deepest.first_time < deepest.last_time            # of the values that exist, not of the NULLs


async def test_values_are_real_samples_never_averages():
    res, _ = await _fetch(PAP2)
    raw = read(_stem(PAP2), "ascii").decode()
    on_the_wire = {float(t) for t in re.findall(r"-?\d+\.\d+(?:E[+-]?\d+)?", raw)}
    seen = 0
    for s in res.series:
        for v in s.vals:
            if v is not None:
                seen += 1
                assert v in on_the_wire, f"{v} is not a value the server sent (an average?)"
        assert len(s.vals) == 150
    assert seen > 2000
    # stride in the right place: sample j is TIME[j*stride]; the file has 36528 samples
    assert res.series[0].stride == 244 and res.series[0].n_total == 36528


async def test_two_variables_one_request_and_units_are_the_files_own():
    res, server = await _fetch(PAP2)
    assert res.requests == 3
    by = {(s.variable, s.depth_index): s for s in res.series}
    assert {v for v, _ in by} == {"TEMP", "PSAL"}
    assert by[("TEMP", 0)].units == "degree_Celsius"
    assert by[("PSAL", 0)].units == "psu"                     # not rewritten to PSS-78 / "1"
    assert by[("PSAL", 0)].standard_name == "sea_water_salinity"
    assert by[("TEMP", 9)].depth_m == 1003.0


async def test_plain_array_single_depth_without_qc():
    res, server = await _fetch(IRMINGSEA)
    assert len(res.series) == 2
    t = next(s for s in res.series if s.variable == "TEMP")
    assert t.depth_index == 0 and t.depth_m == 2965.0         # from the scalar DEPTH[1]
    assert t.qc == [None] * len(t.qc)                         # no QC variable: NULL, not 0 and not 1
    assert t.times[0] == datetime(2003, 8, 30, 12, tzinfo=timezone.utc)   # 19599.5 days since 1950
    assert t.vals[0] == 1.3839 and t.n_total == 143267 and t.stride == 956
    assert next(s for s in res.series if s.variable == "PSAL").standard_name == "sea_water_practical_salinity"
    assert "TEMP.TEMP" not in server.requests[-1][2]


async def test_mbari_r_file_four_dim_grid_float_qc_missing_units_and_celsius_untouched():
    res, _ = await _fetch(MBARI)
    assert len(res.series) == 10
    temp = [s for s in res.series if s.variable == "TEMP"]
    psal = [s for s in res.series if s.variable == "PSAL"]
    assert [s.depth_m for s in temp] == [1.0, 10.0, 20.0, 40.0, 55.0]
    assert {s.units for s in temp} == {"celsius"}             # the file's spelling, not "degree_Celsius"
    assert {s.units for s in psal} == {None}                  # the file's units is " ": no unit declared, none invented
    assert {q for s in res.series for q in s.qc if q is not None} <= {2, 4}   # "2.0" -> 2
    assert all(isinstance(q, int) for s in res.series for q in s.qc if q is not None)
    assert res.citation.endswith("Monterey Bay Aquarium Research Institute.")
    # -1.0E34 (declared fill, QC fill) is NULL
    assert all(v is None or v > -10 for s in temp for v in s.vals)


async def test_a_tail_of_fill_values_is_null_and_does_not_extend_the_series():
    res, _ = await _fetch(T8S165E)
    (s,) = res.series
    assert (s.n_total, s.stride, len(s.vals)) == (22127, 148, 150)
    assert all(v is not None for v in s.vals[:103])
    assert all(v is None for v in s.vals[103:])                # 47 trailing -999.0
    assert s.qc[102] == 2 and set(s.qc[103:]) == {9}
    assert s.last_time == s.times[102] and s.first_time == s.times[0]
    assert s.times[-1] > s.last_time                           # the gap is kept visible, not trimmed away


async def test_a_level_that_is_entirely_fill_stores_no_series():
    dds, das = _dds_das(T0N140W)
    plan = od.plan_file(dds, das, W)
    raw = read(_stem(T0N140W), "ascii").decode()
    # blank out one real depth column (index 1 of the response = depth_index 2) with the declared fill
    head, body = raw.split("\nTEMP[", 1)
    block, rest = body.split("\n\n", 1)
    lines = block.split("\n")
    fixed = [lines[0]] + [re.sub(r"^(\[\d+\], [^,]+), [^,]+", r"\1, -999.0", l) for l in lines[1:]]
    text = head + "\nTEMP[" + "\n".join(fixed) + "\n\n" + rest
    rows, _ = od.decode_response(plan, text)
    assert 2 not in {r.depth_index for r in rows} and len(rows) == 7


async def test_payload_that_does_not_match_its_header_is_rejected_not_guessed():
    dds, das = _dds_das(T0N140W)
    plan = od.plan_file(dds, das, W)
    raw = read(_stem(T0N140W), "ascii").decode()
    cut = raw.replace("[13], -999.0, 25.811, 1.0E33", "")   # a missing row
    # make sure the replacement really changed something in a real row, else this proves nothing
    victim = next(l for l in raw.splitlines() if l.startswith("[149], "))
    truncated = raw.replace(victim + "\n", "", 1)
    assert truncated != raw
    with pytest.raises(od.OpendapError) as e:
        od.decode_response(plan, truncated)
    assert e.value.kind == "rejected"


# ── HTTP behaviour ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", [503, 500, 429])
async def test_a_server_that_cannot_answer_is_unavailable_never_no_data(status):
    server = FixtureServer(status=status)
    with pytest.raises(od.OpendapError) as e:
        await _fetch(T0N140W, server)
    assert e.value.kind == "unavailable"
    assert len(server.requests) == od._RETRIES                # retried, then gave up


async def test_timeout_and_connection_errors_are_unavailable():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as c:
        with pytest.raises(od.OpendapError) as e:
            await od.fetch_file_series(c, T0N140W, W)
    assert e.value.kind == "unavailable"


async def test_404_is_rejected_not_unavailable():
    server = FixtureServer()
    with pytest.raises(od.OpendapError) as e:
        await _fetch("DATA/NOWHERE/OS_NOWHERE_1_D_X.nc", server)
    assert e.value.kind == "rejected" and len(server.requests) == 1   # no retry on a 4xx


async def test_brackets_are_percent_encoded_on_the_wire():
    seen = []

    def spy(request):
        seen.append(str(request.url))
        return FixtureServer().handle(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(spy)) as c:
        await od.fetch_file_series(c, T0N140W, W)
    ascii_url = seen[-1]
    assert "[" not in ascii_url and "%5B0%3A181%3A27004%5D" in ascii_url


async def test_one_refused_variable_does_not_cost_the_file_its_other_variables():
    """The server refuses the combined constraint (real 400 body); the file is then
    read one variable at a time, each answered with real recorded bytes."""
    server = FixtureServer(reject_multi_variable=True)
    res, _ = await _fetch(PAP2, server)
    assert {s.variable for s in res.series} == {"TEMP", "PSAL"} and len(res.series) == 20
    asc = [r for r in server.requests if ".ascii" in r[1]]
    assert len(asc) == 3 and res.requests == 5                # combined (refused) + one per variable


async def test_refused_single_variable_is_reported_not_swallowed():
    server = FixtureServer()
    async with httpx.AsyncClient(transport=server.transport()) as c:
        with pytest.raises(od.OpendapError) as e:
            await od.fetch_file_series(c, K276, {"sea_water_temperature"})   # constraint was never recorded -> 400
    assert e.value.kind == "rejected"


async def test_bottle_profile_raises_unsupported_after_two_requests():
    server = FixtureServer()
    with pytest.raises(od.UnsupportedFile):
        await _fetch(BATS_BTL, server)
    assert len(server.requests) == 2                          # .dds + .das, no data request


# ── selection, change marker, run planning (real index rows) ────────────────


@pytest.fixture(scope="module")
def tao_rows():
    return idx.parse_index((FIX / "index_T0N140W.txt").read_text(encoding="utf-8"))


def _cands(rows, ref="5100311"):
    return [{"station_ref": ref, **r} for r in rows]


def _covered(row, others):
    """Is row's span inside the union of the others' spans (independent of the code under test)?"""
    spans = sorted((o["start_time"], o["end_time"]) for o in others)
    merged = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return any(s <= row["start_time"] and row["end_time"] <= e for s, e in merged)


def test_selection_is_bounded_delayed_first_and_never_leaves_out_uncovered_time(tao_rows):
    chosen = od.select_files(_cands(tao_rows))
    for name in sorted(od.HISTORY_STANDARD_NAMES):
        carriers = [r for r in tao_rows if name in r["parameters"]]
        picked = [r for r in carriers if r["file"] in chosen and name in chosen[r["file"]][1]]
        omitted = [r for r in carriers if r not in picked]
        assert len(picked) <= od.MAX_FILES_PER_SERIES
        # a file is left out only because the cap is full or its time is already covered
        for r in omitted:
            assert len(picked) == od.MAX_FILES_PER_SERIES or _covered(r, picked), (name, r["file"])
        # a real-time file is taken only where no delayed file already covers its time
        d_picked = [r for r in picked if r["data_mode"] == "D"]
        for r in picked:
            if r["data_mode"] == "R":
                assert not _covered(r, d_picked)
    east = [r for r in tao_rows if r["file"] in chosen and "eastward_sea_water_velocity" in chosen[r["file"]][1]]
    assert len(east) == 30 and sum(r["data_mode"] == "D" for r in east) == 28   # 37 D carry it; 9 of them duplicate others' span
    hourly_dup = "OS_T0N140W_DM124A-20150323_D_CURR_hourly.nc"
    assert all(not r["file"].endswith(hourly_dup) for r in east)                 # same 10 months as the 20-min file


def test_a_file_is_attributed_only_the_names_it_carries(tao_rows):
    chosen = od.select_files(_cands(tao_rows))
    by_file = {r["file"]: r for r in tao_rows}
    for f, (_, names) in chosen.items():
        assert names <= set(by_file[f]["parameters"]) & W


def test_the_best_placed_file_of_every_station_comes_first():
    sample = idx.parse_index((FIX / "index_T0N140W.txt").read_text(encoding="utf-8"))
    cands = _cands(sample, "A") + _cands(sample, "B")
    ranks = od.select_files(cands)
    n0 = sum(1 for r, _ in ranks.values() if r == 0)
    assert 1 < n0 < len(ranks)
    plan = od.plan_run(cands, {}, max_files=n0 + 3)
    got = [ranks[f][0] for f, _ in plan["todo"]]
    assert got == sorted(got) and got[:n0] == [0] * n0 and all(r > 0 for r in got[n0:])
    assert plan["needed"] == len(ranks) and plan["remaining"] == len(ranks) - (n0 + 3)
    capped = od.plan_run(cands, {}, max_files=n0)
    assert {ranks[f][0] for f, _ in capped["todo"]} == {0}


def _row(**kw):
    base = {"file": "DATA/X/OS_X_1_D_T.nc", "gdac_update_date": None, "date_update": None,
            "size_bytes": None, "end_time": None}
    base.update(kw)
    return base


def test_change_marker_order_and_garbage_stamps():
    t = lambda y: datetime(y, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    assert od.change_marker(_row(gdac_update_date=t(2020), date_update=t(2019))) == "g:2020-03-04T05:06:07Z"
    assert od.change_marker(_row(gdac_update_date=None, date_update=t(2019))) == "d:2019-03-04T05:06:07Z"
    # ALOHA's GDAC_UPDATE_DATE of "50" parses to year 50: not a stamp
    assert od.change_marker(_row(gdac_update_date=datetime(50, 1, 1, tzinfo=timezone.utc),
                                 size_bytes=10, end_time=t(2011))) == "s:10:2011-03-04T05:06:07Z"
    assert od.change_marker(_row()) is None


def test_plan_run_skips_unchanged_refetches_changed_and_never_retries_what_cannot_be_sampled(tao_rows):
    cands = _cands(tao_rows)
    files = od.select_files(cands)
    f_ok, (_, n_ok) = next(iter(files.items()))
    by_file = {r["file"]: r for r in tao_rows}
    marker = od.change_marker(by_file[f_ok])
    fetched = {f_ok: {"outcome": "ok", "change_marker": marker, "standard_names": sorted(n_ok)}}
    todo = {f for f, _ in od.plan_run(cands, fetched, 10 ** 6)["todo"]}
    assert f_ok not in todo and len(todo) == len(files) - 1                        # unchanged: skipped

    fetched[f_ok]["change_marker"] = "g:1999-01-01T00:00:00Z"                         # republished
    assert f_ok in {f for f, _ in od.plan_run(cands, fetched, 10 ** 6)["todo"]}

    fetched[f_ok] = {"outcome": "ok", "change_marker": marker, "standard_names": []}  # now serves a new name
    assert f_ok in {f for f, _ in od.plan_run(cands, fetched, 10 ** 6)["todo"]}

    fetched[f_ok] = {"outcome": "ok", "change_marker": marker, "standard_names": sorted(n_ok)}
    # A file known to hold nothing sampleable gives up its place: the hourly twin of a
    # 20-minute current-meter file is skipped as "covered" until the 20-minute file is out.
    twin = next(r["file"] for r in tao_rows if r["file"].endswith("DM124A-20150323_D_CURR_hourly.nc"))
    main_file = next(r["file"] for r in tao_rows if r["file"].endswith("DM124A-20150323_D_CURR_20min.nc"))
    assert twin not in files and main_file in files
    names_main = files[main_file][1]
    fetched = {main_file: {"outcome": "empty", "change_marker": od.change_marker(by_file[main_file]),
                           "standard_names": sorted(names_main)}}
    plan = od.plan_run(cands, fetched, 10 ** 6)
    assert main_file not in {f for f, _ in plan["todo"]}                    # never asked again
    assert twin in {f for f, _ in plan["todo"]}                              # ... and its place went to the next file


def test_a_refused_file_waits_for_its_marker_and_frees_its_place(tao_rows):
    cands = _cands(tao_rows)
    files = od.select_files(cands)
    by_file = {r["file"]: r for r in tao_rows}
    main_file = next(r["file"] for r in tao_rows if r["file"].endswith("DM124A-20150323_D_CURR_20min.nc"))
    twin = next(r["file"] for r in tao_rows if r["file"].endswith("DM124A-20150323_D_CURR_hourly.nc"))
    marker = od.change_marker(by_file[main_file])
    refused = {main_file: {"outcome": "refused", "change_marker": marker, "standard_names": []}}
    todo = {f for f, _ in od.plan_run(cands, refused, 10 ** 6)["todo"]}
    assert main_file not in todo and twin in todo                       # not asked again; its place moves on
    refused[main_file]["change_marker"] = "g:1999-01-01T00:00:00Z"      # the GDAC republished it
    assert main_file in {f for f, _ in od.plan_run(cands, refused, 10 ** 6)["todo"]}
    refused[main_file] = {"outcome": "refused", "change_marker": None, "standard_names": []}
    row_without_marker = [dict(r, gdac_update_date=None, date_update=None, size_bytes=None, end_time=None)
                          if r["file"] == main_file else r for r in tao_rows]
    assert main_file not in {f for f, _ in od.plan_run(_cands(row_without_marker), refused, 10 ** 6)["todo"]}


def test_a_null_marker_is_fetched_once_and_then_left_alone(tao_rows):
    rows = [dict(r, gdac_update_date=None, date_update=None, size_bytes=None, end_time=None)
            for r in tao_rows[:6]]
    cands = _cands(rows)
    assert all(od.change_marker(r) is None for r in rows)
    first = od.plan_run(cands, {}, 100)["todo"]
    assert first
    fetched = {f: {"outcome": "ok", "change_marker": None, "standard_names": sorted(n)} for f, n in first}
    assert od.plan_run(cands, fetched, 100)["todo"] == []
