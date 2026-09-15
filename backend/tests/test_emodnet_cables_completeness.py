# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""EMODnet publishes 11 cable layers. We fetched 7, and two of the four we
skipped were the largest French datasets in the service.

Counted at the WFS on 2026-09-15: shomcables 603, pcablesshom 142,
cicacables 29, maltacables 6 — 780 features against the 1,255 we held.

⚠️ They were not forgotten. `rules/layers/submarine-cables.md` records the
decision: SHOM "skipped at design time" for thin S-57 attribution, CICA and
Malta "outside Baltic focus this iteration". The reasons are true; the rule
that we fetch everything a provider publishes and choose afterwards overrules
them, because a layer nobody fetches cannot be chosen from later.

Three defects surfaced while wiring them in, and each one is quiet:

* `required = 6` was hardcoded beside a note asking whoever changed the layer
  count to revisit it. The count went 7 → 11. Six of eleven would have passed
  the guard, TRUNCATEd the table and re-filled it with 45% of the cables.
* `sigcables.inst_year` was hardcoded None while the layer fills it on all 60
  of 60 features — and the column name lies: it holds `dd/mm/yyyy`, so an int
  cast would also have produced None, just as quietly.
* Rijkswaterstaat publishes `KB0039` as five separate line features and
  `KB0048` as two. `ON CONFLICT DO NOTHING` dropped the extras, so two cables
  were drawn from one segment each — a truncated route that looks complete.
"""
import pytest

from ingestion import emodnet_cables_ingest as mod

# The four added on 2026-09-15, with the feature counts read at the source.
ADDED = {
    "shomcables": 603,
    "pcablesshom": 142,
    "cicacables": 29,
    "maltacables": 6,
}


def _feat(coords, **props):
    return {"type": "Feature",
            "geometry": {"type": "MultiLineString", "coordinates": coords},
            "properties": props}


# ─────────────────────────────────────────────────────────────────────────────
# The layers themselves.
# ─────────────────────────────────────────────────────────────────────────────

def test_every_added_layer_is_fetched_and_has_a_mapper():
    missing_layer = [l for l in ADDED if l not in mod.LAYERS]
    assert missing_layer == [], (
        f"{missing_layer} are not in LAYERS — they will not be fetched at all")
    missing_mapper = [l for l in ADDED if l not in mod.LAYER_MAPPERS]
    assert missing_mapper == [], (
        f"{missing_mapper} are fetched but have no mapper. fetch_all_layers "
        "logs a warning and yields an empty list — the layer reads as empty "
        "upstream rather than as unwired here.")


def test_every_fetched_layer_has_a_mapper_and_the_reverse():
    assert sorted(mod.LAYERS) == sorted(mod.LAYER_MAPPERS), (
        "LAYERS and LAYER_MAPPERS disagree. A layer in one and not the other "
        "is either fetched and discarded, or mapped and never requested.")


# ─────────────────────────────────────────────────────────────────────────────
# ⛔ The TRUNCATE threshold. This one deletes data when it is wrong.
# ─────────────────────────────────────────────────────────────────────────────

def test_the_truncate_threshold_is_derived_from_the_layer_list():
    """⛔ `required` used to be the literal 6, for 7 layers.

    With 11 layers, six succeeding would have been "enough": TRUNCATE the
    table, insert 45% of the cables, report success. A TRUNCATE does not come
    back.
    """
    import ast
    import inspect
    import textwrap

    from domains import cables

    # ⛔ Parsed, not grepped. The first version of this test searched the text
    # for "required = 6" and went red on the COMMENT that explains why the 6 is
    # gone — a guard that fires on its own documentation is a guard people
    # delete.
    tree = ast.parse(textwrap.dedent(inspect.getsource(cables.sync_submarine_cables)))
    assigns = [n for n in ast.walk(tree)
               if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "required" for t in n.targets)]
    assert len(assigns) == 1, f"expected one `required =`, found {len(assigns)}"
    value = assigns[0].value
    assert not isinstance(value, ast.Constant), (
        f"the TRUNCATE threshold is the literal {getattr(value, 'value', '?')!r}. "
        "A literal survives the next layer addition and silently lets a partial "
        "fetch replace the whole table.")
    names = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
    assert "LAYERS" in names, (
        f"the threshold is computed from {sorted(names)}, which does not "
        "include the layer list it is supposed to track")


def test_the_threshold_tolerates_exactly_one_failed_layer():
    """The intent, stated as a number rather than as a comment."""
    required = max(1, len(mod.LAYERS) - 1)
    assert required == len(mod.LAYERS) - 1
    assert required >= 10, (
        f"with {len(mod.LAYERS)} layers the guard demands only {required} — "
        "more than one layer could fail and still replace the table")


# ─────────────────────────────────────────────────────────────────────────────
# The date that was not a date, in a column whose name says year.
# ─────────────────────────────────────────────────────────────────────────────

def test_sigcables_reads_the_year_it_publishes():
    f = _feat([[[1.0, 2.0], [1.1, 2.1]]],
              name="CABLE A", inst_year="01/05/1995", status="2",
              location="Offshore")
    row = mod.LAYER_MAPPERS["sigcables"](f)
    assert row["inst_year"] == 1995, (
        f"inst_year came out {row['inst_year']!r}. The layer fills this field "
        "on all 60 of 60 features and it was hardcoded None.")


def test_a_slash_date_is_not_read_as_a_year():
    """⛔ The column is called inst_year and holds dd/mm/yyyy.

    `int("01/05/1995")` raises and `_coerce_int` turns that into None — so the
    obvious fix would have looked exactly like the bug it replaced.
    """
    assert mod._coerce_int("01/05/1995") is None, (
        "the fixture assumption is wrong; re-check why this guard exists")
    assert mod._parse_slash_date("01/05/1995").year == 1995
    assert mod._parse_slash_date("1995-05-01") is None, "iso dates are not this format"


def test_a_single_space_is_not_a_date():
    """SIGCables writes ' ' — one space — in its blank `dism_year` cells.

    ⛔ `if v:` calls that present. Every parser here strips first.
    """
    assert mod._parse_slash_date(" ") is None
    assert mod._parse_slash_date("") is None
    assert mod._parse_slash_date(None) is None


def test_sigcables_does_not_put_a_code_in_the_words_column():
    """`status` is "1" or "2" here, against "ACTIVE"/"inUse"/"Permanent"
    elsewhere. A panel rendering "Status: 2" asserts something we cannot
    support — the vocabulary is nieustalone."""
    f = _feat([[[1.0, 2.0], [1.1, 2.1]]], name="CABLE A", status="2")
    assert mod.LAYER_MAPPERS["sigcables"](f)["status"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Segments of one cable, published as separate features.
# ─────────────────────────────────────────────────────────────────────────────

def test_segments_sharing_an_id_are_merged_not_dropped():
    rows = [
        {"source_layer": "rijkscables", "source_id": "KB0039",
         "coordinates": [[[0.0, 0.0], [1.0, 1.0]]], "name": "A"},
        {"source_layer": "rijkscables", "source_id": "KB0039",
         "coordinates": [[[1.0, 1.0], [2.0, 2.0]]], "name": "A"},
        {"source_layer": "rijkscables", "source_id": "KB0040",
         "coordinates": [[[5.0, 5.0], [6.0, 6.0]]], "name": "B"},
    ]
    merged, n = mod._merge_segments(rows, "rijkscables")

    assert n == 1, f"reported {n} merges, expected 1"
    assert len(merged) == 2, "the two cables did not come out as two rows"
    kb39 = next(r for r in merged if r["source_id"] == "KB0039")
    assert len(kb39["coordinates"]) == 2, (
        "the second segment's geometry was thrown away — the cable is drawn "
        "short, which on a map is indistinguishable from a complete cable")


def test_a_layer_with_no_repeats_is_left_alone():
    rows = [{"source_layer": "x", "source_id": f"id{i}",
             "coordinates": [[[float(i), 0.0], [float(i), 1.0]]]} for i in range(4)]
    merged, n = mod._merge_segments(rows, "x")
    assert n == 0 and len(merged) == 4


def test_cicacables_does_not_use_a_condition_as_an_identity():
    """⛔ All 29 features carry one of two `name` values —
    "CABLES DE TELEFONO ABANDONADOS" (17) and "…OPERATIVOS" (12).

    The sigcables mapper uses `name` as `source_id`; copying that here would
    have collapsed 29 rows to 2, silently, with the sync reporting success.
    """
    a = _feat([[[1.0, 2.0], [1.1, 2.1]]], name="CABLES DE TELEFONO ABANDONADOS")
    b = _feat([[[9.0, 8.0], [9.1, 8.1]]], name="CABLES DE TELEFONO ABANDONADOS")
    ra, rb = mod.LAYER_MAPPERS["cicacables"](a), mod.LAYER_MAPPERS["cicacables"](b)

    assert ra["source_id"] != rb["source_id"], (
        "two different cables share an id; ON CONFLICT DO NOTHING drops one")
    assert "ABANDONADOS" not in (ra["source_id"] or ""), (
        "the condition string leaked into the identifier")
    assert ra["name"] is None, "a condition was stored as the cable's name"
    assert ra["status"] == "Abandoned", "the condition was lost entirely"
    assert mod.LAYER_MAPPERS["cicacables"](
        _feat([[[3.0, 4.0], [3.1, 4.1]]],
              name="CABLES DE TELEFONO OPERATIVOS"))["status"] == "Operational"


def test_an_identical_geometry_hashes_the_same():
    """The flip side: two features that ARE the same line should merge."""
    a = _feat([[[1.0, 2.0], [1.1, 2.1]]], name="CABLES DE TELEFONO OPERATIVOS")
    b = _feat([[[1.0, 2.0], [1.1, 2.1]]], name="CABLES DE TELEFONO OPERATIVOS")
    assert (mod.LAYER_MAPPERS["cicacables"](a)["source_id"]
            == mod.LAYER_MAPPERS["cicacables"](b)["source_id"])


def test_the_shom_layers_do_not_invent_a_name_from_an_id():
    """SHOM publishes no name at all — only an INSPIRE identifier.

    ⛔ Repeating the id as the name would tell a reader that someone calls this
    cable "FR 0000165900 00001".
    """
    f = _feat([[[1.0, 2.0], [1.1, 2.1]]],
              inspireid="FR 0000165900 00001", catcbl=4.0, status="4")
    row = mod.LAYER_MAPPERS["shomcables"](f)
    assert row["source_id"] == "FR 0000165900 00001"
    assert row["name"] is None
    assert row["status"] is None, "a bare code went into the words column"
    assert row["cable_type"] == "Telecommunication", (
        "cable_type must come from the publisher's own layer title, not from "
        "the unverified S-57 `catcbl` code")
    power = mod.LAYER_MAPPERS["pcablesshom"](f)
    assert power["cable_type"] == "Power"
    assert power["source_layer"] == "pcablesshom"


def test_a_feature_with_no_geometry_is_skipped_everywhere():
    """Positive control for the skip path across all four new mappers."""
    empty = {"type": "Feature", "geometry": None, "properties": {"name": "x"}}
    for layer in ADDED:
        assert mod.LAYER_MAPPERS[layer](empty) is None, f"{layer} accepted a null geometry"


@pytest.mark.parametrize("layer", sorted(ADDED))
def test_each_new_mapper_emits_the_full_normalized_shape(layer):
    """⛔ A missing key is a KeyError inside the sync's row loop, which is
    caught per row — so a mapper one field short drops its whole layer with a
    warning per feature and no summary."""
    f = _feat([[[1.0, 2.0], [1.1, 2.1]]],
              name="Go-1 Mediterranean Cable System",
              inspireid="FR 0000165900 00001", catcbl=1.0, status="4")
    row = mod.LAYER_MAPPERS[layer](f)
    assert row is not None, f"{layer} rejected a well-formed feature"
    expected = {"source_layer", "source_id", "name", "operator", "cable_type",
                "voltage_kv", "inst_year", "status", "location", "coordinates"}
    assert set(row) == expected, f"{layer} emits {sorted(set(row) ^ expected)}"
    assert row["source_layer"] == layer


@pytest.mark.asyncio
async def test_the_fetch_path_actually_merges(monkeypatch):
    """⛔ Guard the call site, not only the helper.

    The first version of this file tested `_merge_segments` directly and went
    green with the call removed from `fetch_all_layers` — a helper nobody calls
    is a helper that fixes nothing. This drives the real generator.
    """
    async def _fake_fetch(_client, layer):
        if layer != "rijkscables":
            return []
        return [
            _feat([[[0.0, 0.0], [1.0, 1.0]]], kabel_nr="KB0039", naam="A"),
            _feat([[[1.0, 1.0], [2.0, 2.0]]], kabel_nr="KB0039", naam="A"),
            _feat([[[5.0, 5.0], [6.0, 6.0]]], kabel_nr="KB0040", naam="B"),
        ]

    monkeypatch.setattr(mod, "_fetch_one_layer", _fake_fetch)

    out = {}
    async for layer, rows in mod.fetch_all_layers():
        out[layer] = rows

    rows = out["rijkscables"]
    assert len(rows) == 2, (
        f"the fetch path yielded {len(rows)} rows for two cables published as "
        "three features — the duplicate is still reaching the INSERT, where "
        "ON CONFLICT DO NOTHING drops it without a word")
    kb39 = next(r for r in rows if r["source_id"] == "KB0039")
    assert len(kb39["coordinates"]) == 2, (
        "both segments must survive the merge; one alone draws half a cable")
