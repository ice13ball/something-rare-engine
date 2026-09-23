# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A dam must not wear a neighbour's hazard rating.

`_enrich_tailings_from_grid` matches a GRID-Arendal facility to the nearest
WAPHA dam within 5 km. The exclusion was `data_source IS DISTINCT FROM 'grid'`,
which skipped GRID's own inserted rows but NOT the ones a previous facility had
already enriched ('grid-enriched'). owner_company, operator,
construction_year and hazard_raw are assigned unconditionally — no COALESCE —
so a second facility overwrote the first one's attributes outright.

Measured against the live GRID API on 2026-09-10:

    2,144 facilities fetched
    1,406 dams matched
      224 of those dams were the nearest match for MORE THAN ONE facility
      473 overwrites in a single pass
    worst: dam id 7832 claimed by 22 different facilities — its hazard rating
           and owner were whichever facility came last in the API's ordering

⛔ This portal mirrors its sources 1:1. Attributing GRID's record of facility A
to dam B is not mirroring, it is misattribution, and `hazard_raw` is a safety
rating the operator published about a specific facility. A facility that cannot claim an unclaimed dam is stored as its own row,
which keeps both sources intact and invents no link.
"""
import pathlib
import re

ROOT       = pathlib.Path(__file__).resolve().parents[2]
EXTRACTIVE = ROOT / "backend" / "domains" / "land" / "extractive.py"
SCHEMA     = ROOT / "backend" / "domains" / "land" / "schema_orchestrator.py"

_SRC = EXTRACTIVE.read_text(encoding="utf-8")


def _enrich_body() -> str:
    i = _SRC.index("async def _enrich_tailings_from_grid")
    j = _SRC.index("\nasync def ", i + 10)
    return _SRC[i:j]


def test_the_fixture_isolated_the_enrichment():
    body = _enrich_body()
    assert "tailings_dams" in body and len(body) > 800, (
        "fixture problem: _enrich_tailings_from_grid did not slice out"
    )


def test_an_already_enriched_dam_cannot_be_claimed_again():
    body = _enrich_body()
    # ⚠️ Anchor on ST_DWithin, not on the first "SELECT id FROM tailings_dams".
    # A second such SELECT now precedes this one — the lookup by
    # grid_facility_id that makes a re-run idempotent — and slicing from the
    # first match would test the wrong query while still passing.
    sel = body[body.index("ST_DWithin"):]
    sel = sel[:sel.index('"""')]
    assert "grid_facility_id IS NULL" in sel, (
        "the match query does not exclude rows a facility has already claimed, "
        "so the second facility within 5 km overwrites the first — 473 times in "
        "one measured pass"
    )
    # ⛔ It must NOT be excluded by data_source. That was the 2026-09-22 bug:
    # grid_facility_id was added after the last successful run, so it was NULL
    # on all 1,648 existing rows; the key lookup found nothing and a
    # data_source exclusion hid those same rows from the spatial match too.
    # Every facility fell through to INSERT — 1,584 duplicates, deleted by hand.
    # An idempotency key nothing has populated is not idempotency.
    assert "data_source IS DISTINCT FROM" not in sel, (
        "the match query is excluding by data_source again. A legacy row that "
        "predates grid_facility_id carries no key, so this hides it from BOTH "
        "lookup paths and the facility is inserted as a duplicate instead"
    )


def test_the_overwrite_is_still_unconditional_so_the_guard_above_is_load_bearing():
    # ⛔ If every field the UPDATE touches were COALESCEd, the test above could
    # be deleted without anything going red. Prove the damage is still possible,
    # so the guard means something. This is the "prove both sides non-empty" rule.
    #
    # ⚠️ This used to sample `risk_class`, which no longer exists: it was this
    # platform's six-tier collapse of the source rating and was removed
    # 2026-09-22. The invariant did not change — only the field that witnesses
    # it. `hazard_raw` is the better witness anyway: it IS the operator's own
    # safety rating, which is what misattribution would put on the wrong dam.
    body = _enrich_body()
    upd = body[body.index("UPDATE tailings_dams SET"):]
    upd = upd[:upd.index('"""')]
    for col in ("hazard_raw", "owner_company", "operator"):
        assert re.search(rf"{col}\s*=\s*\$\d", upd), f"{col} assignment vanished"
        assert f"COALESCE({col}" not in upd, (
            f"{col} is now COALESCEd — re-read whether the exclusion above is "
            "still what protects the attribution, rather than leaving a guard "
            "that binds nothing"
        )


def test_the_facility_key_is_stored_so_the_link_can_be_audited():
    body = _enrich_body()
    assert "ubc_number" in body, (
        "GRID's own facility key is never read, so the link is re-derived from "
        "bare proximity on every run and nobody can check which facility a "
        "dam's hazard rating describes"
    )
    assert "grid_facility_id" in body, "the key is read but never stored"
    ddl = SCHEMA.read_text(encoding="utf-8")
    assert re.search(r"ADD COLUMN IF NOT EXISTS grid_facility_id\b", ddl), (
        "grid_facility_id has no column, or is added without IF NOT EXISTS — "
        "the VPS re-runs the schema on every deploy"
    )


def test_both_write_paths_carry_the_key():
    # The insert branch matters as much as the update branch: a GRID facility
    # stored as its own row is exactly the case that must stay traceable.
    body = _enrich_body()
    upd = body[body.index("UPDATE tailings_dams SET"):]
    ins = body[body.index("INSERT INTO tailings_dams"):]
    assert "grid_facility_id" in upd[:upd.index("INSERT INTO tailings_dams")], (
        "the enrichment UPDATE does not record which facility it came from"
    )
    assert "grid_facility_id" in ins, (
        "a GRID facility inserted as its own row carries no GRID id"
    )


# ⛔ THE TEST THAT WOULD HAVE CAUGHT IT.
#
# Every assertion above reads this module as TEXT. On 2026-09-22 that let a
# deletion take `GRID_TAILINGS_API` with it — the constant sat between the dead
# function being removed and the next `def`, so a slice between them swallowed
# it. All the source-shape guards stayed green; the sync raised
# `NameError: name 'GRID_TAILINGS_API' is not defined` on its first real run,
# in production, 277 ms in.
#
# This one IMPORTS the module and resolves the global names each function
# actually references. It needs no database and no network, and a missing
# global fails it immediately. See memory feedback_tests_must_execute_not_grep:
# grep is for the shape of code, never for whether it runs.
import builtins
import dis
import importlib
import types


def _global_names(fn) -> set[str]:
    """Only LOAD_GLOBAL, never LOAD_ATTR.

    ⚠️ `code.co_names` mixes the two: `conn.execute(...)` puts "execute" there
    even though it is an attribute lookup on a local. A first draft of this test
    used co_names and reported 40 false positives, which is worse than no test —
    a guard nobody can read is a guard everybody turns off.
    """
    return {
        ins.argval
        for ins in dis.get_instructions(fn.__code__)
        if ins.opname == "LOAD_GLOBAL"
    }


def test_every_global_the_module_references_actually_exists():
    mod = importlib.import_module("domains.land.extractive")
    missing: list[str] = []
    for obj_name in dir(mod):
        fn = getattr(mod, obj_name)
        if not isinstance(fn, types.FunctionType) or fn.__module__ != mod.__name__:
            continue
        for name in _global_names(fn):
            if name in mod.__dict__ or hasattr(builtins, name):
                continue
            missing.append(f"{obj_name} -> {name}")
    assert not missing, (
        "these names are referenced but resolve to nothing at module level — "
        "the function raises NameError the moment that line runs:\n  "
        + "\n  ".join(sorted(set(missing)))
    )
