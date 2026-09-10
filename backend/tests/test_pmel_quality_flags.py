# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""PMEL publishes a quality flag beside every value. We must ask for it.

The OceanSITES sync's docstring described PMEL ERDDAP as "daily QC'd" and the
module fetched `station,time,T_25` — the flag column sat next to T_25 and was
never requested. PMEL's own metadata, verbatim:

    QT_5025 description: "Quality: 0=missing data, 1=highest, 2=standard,
    3=lower, 4=questionable, 5=bad, -9=contact Dai.C.McClurg@noaa.gov.
    To get probably valid data only, request QT_5025>=1 and QT_5025<=3."

⚠️ Measured against the live query on 2026-09-10, before the fix: 57 stations
for SST, 53 for SSS, 65 for air temperature — every single value flag 2, none
above 3. So no bad reading was reaching anyone. The defect was that nothing
would have stopped one. The guard is written for the day PMEL flags something,
not for today.

⛔ The rejected value is dropped but its flag is kept: "we withheld this" and
"this station has no sensor" must not render as the same blank.
"""
import ast
import json
import pathlib
import sys

import pytest

PMEL   = pathlib.Path(__file__).resolve().parents[1] / "ingestion" / "pmel_erddap.py"
FRONT  = pathlib.Path(__file__).resolve().parents[2] / "frontend"
PANEL  = FRONT / "src" / "components" / "panels" / "ocean" / "OceansitesPanel.tsx"
LOCALES = FRONT / "public" / "locales"

_SRC  = PMEL.read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)


def _datasets() -> list[tuple[str, list[str], list[str]]]:
    for node in _TREE.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "_DATASETS":
            return ast.literal_eval(node.value)
    return []


def test_the_fixture_parsed_the_dataset_table():
    ds = _datasets()
    assert len(ds) >= 5, f"fixture problem: parsed {ds!r} out of pmel_erddap.py"
    assert all(len(t) == 3 for t in ds), (
        "each entry must be (dataset, values, quality) — a two-tuple means the "
        "quality column was dropped again"
    )


def test_every_dataset_asks_for_a_quality_column():
    naked = [d for d, _v, q in _datasets() if not q]
    assert not naked, (
        f"these PMEL datasets are fetched without their quality flag: {naked}. "
        "PMEL ships the flag next to the value and tells you to filter on it."
    )


def test_the_quality_columns_are_actually_sent_to_erddap():
    # ⛔ Declaring them in _DATASETS proves nothing if the URL builder ignores
    # them. This is the call-site half — the lesson MOSAIC and offshore both
    # taught: the helper was right, the call site was not.
    cols = [n for n in ast.walk(_TREE)
            if isinstance(n, ast.Assign)
            and any(getattr(t, "id", "") == "cols" for t in n.targets)]
    assert cols, "fixture problem: no `cols = ...` assignment found"
    built = ast.unparse(cols[0].value)
    assert "quality" in built, (
        f"the ERDDAP column list is built as {built} — the quality variables "
        "are declared but never requested"
    )


def test_a_flag_the_publisher_calls_bad_is_refused():
    assert "_ACCEPTABLE_QC" in _SRC, "the accept-list is gone"
    acc = next(ast.literal_eval(n.value) for n in _TREE.body
               if isinstance(n, ast.Assign)
               and any(getattr(t, "id", "") == "_ACCEPTABLE_QC" for t in n.targets))
    assert set(acc) == {1, 2, 3}, (
        f"accepted flags are {acc}; PMEL's own instruction is >=1 and <=3, and "
        "0 means missing data, 4 questionable, 5 bad"
    )
    assert "flag not in _ACCEPTABLE_QC" in _SRC, (
        "nothing filters on the accept-list, so it is decoration"
    )


def test_a_withheld_reading_is_named_rather_than_left_blank():
    panel = PANEL.read_text(encoding="utf-8")
    assert "qcWithheld" in panel and "withheld" in panel, (
        "the panel does not distinguish a reading PMEL rejected from a station "
        "that has no sensor — 'missing' and 'broken' are sharing a code path"
    )
    locales = sorted(p for p in LOCALES.iterdir() if (p / "panels.json").is_file())
    assert len(locales) >= 2, "fixture problem: fewer than two locales discovered"
    missing = {}
    for loc in locales:
        d = json.loads((loc / "panels.json").read_text(encoding="utf-8"))
        gone = [k for k in ("qcWithheld", "qcLowered") if k not in d.get("oceansites", {})]
        if gone:
            missing[loc.name] = gone
    assert not missing, f"quality-flag wording missing per locale: {missing}"


def test_a_station_whose_every_value_was_rejected_does_not_survive_as_data():
    # The final filter used to keep any station with a key other than obs_time.
    # `qc` is a key. Without this, a station whose whole reading PMEL called bad
    # would still be stored as if it carried one.
    tail = _SRC[_SRC.index("Drop entries that ended up"):]
    assert '"obs_time", "qc"' in tail or "'obs_time', 'qc'" in tail, (
        "the drop-empty filter counts `qc` as a reading, so a fully-rejected "
        "station is stored as though it had data"
    )


# ── The executing half ──────────────────────────────────────────────────────
# Everything above reads the source. None of it would notice a merge loop that
# collects the flag and then uses the value anyway.

sys.path.insert(0, str(PMEL.parents[1]))


def _rows(*triples):
    """ERDDAP row shape: [station, time, *values, *quality]."""
    return list(triples)


@pytest.mark.asyncio
async def test_a_flagged_value_is_withheld_while_a_good_one_survives(monkeypatch):
    import ingestion.pmel_erddap as m

    payload = {
        "pmelTaoDySst":  _rows(["0n110w", "2026-09-01T12:00:00Z", 21.6, 2],
                               ["8s165e", "2026-09-01T12:00:00Z", 29.9, 5]),
        "pmelTaoDySss":  _rows(["8s165e", "2026-09-01T12:00:00Z", 35.1, 2]),
        "pmelTaoDyAirt": _rows(["2n140w", "2026-09-01T12:00:00Z", 25.0, 4]),
        "pmelTaoDyW":    [],
        "pmelTaoDyBp":   [],
    }

    async def fake(client, dataset, variables, quality, since_iso):
        return payload[dataset]

    monkeypatch.setattr(m, "_fetch_dataset", fake)
    obs = await m.fetch_pmel_observations()

    # A clean flag-2 reading is kept.
    assert obs["0n110w"]["wtmp"] == 21.6
    assert obs["0n110w"]["qc"]["wtmp"] == 2

    # PMEL called this one BAD (5). The value must not be served...
    assert "wtmp" not in obs["8s165e"], (
        "a reading PMEL flagged 5 (bad) reached the panel"
    )
    # ...but it must be nameable, or the panel shows the same blank a station
    # with no sensor shows.
    assert obs["8s165e"]["qc"]["wtmp"] == 5
    # and its OTHER, clean variable is untouched.
    assert obs["8s165e"]["sss"] == 35.1

    # A station whose only reading was rejected must not survive as data.
    assert "2n140w" not in obs, (
        "a station with nothing but a questionable (4) reading was stored as "
        "though it carried an observation"
    )


@pytest.mark.asyncio
async def test_wind_needs_both_flags_because_we_derive_from_both(monkeypatch):
    import ingestion.pmel_erddap as m

    # Speed vouched for (2), direction called bad (5). We compute speed AND
    # direction from u/v, so half a blessing is not a blessing.
    payload = {"pmelTaoDyW": _rows(["0n110w", "2026-09-01T12:00:00Z", -3.0, -1.5, 2, 5]),
               "pmelTaoDySst": [], "pmelTaoDySss": [], "pmelTaoDyAirt": [], "pmelTaoDyBp": []}

    async def fake(client, dataset, variables, quality, since_iso):
        return payload[dataset]

    monkeypatch.setattr(m, "_fetch_dataset", fake)
    obs = await m.fetch_pmel_observations()
    assert obs == {}, (
        f"wind survived with a direction PMEL called bad: {obs!r} — the worst "
        "of the two flags must decide"
    )
