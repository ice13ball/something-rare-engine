# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A dam must not wear a neighbour's hazard rating.

`_enrich_tailings_from_grid` matches a GRID-Arendal facility to the nearest
WAPHA dam within 5 km. The exclusion was `data_source IS DISTINCT FROM 'grid'`,
which skipped GRID's own inserted rows but NOT the ones a previous facility had
already enriched ('grid-enriched'). risk_class, owner_company, operator,
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
to dam B is not mirroring, it is misattribution, and risk_class is a safety
rating. A facility that cannot claim an unclaimed dam is stored as its own row,
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
    sel = body[body.index("SELECT id FROM tailings_dams"):]
    sel = sel[:sel.index('"""')]
    assert "'grid-enriched'" in sel, (
        "the match query does not exclude dams a previous GRID facility already "
        "enriched, so the second facility within 5 km overwrites the first — "
        "473 times in one measured pass"
    )
    assert "'grid'" in sel, (
        "the match query no longer excludes GRID's own inserted rows either"
    )


def test_the_overwrite_is_still_unconditional_so_the_guard_above_is_load_bearing():
    # ⛔ If someone COALESCEd risk_class, the test above could be deleted without
    # anything going red. Prove the damage is still possible, so the guard means
    # something. This is the "prove both sides non-empty" rule.
    body = _enrich_body()
    upd = body[body.index("UPDATE tailings_dams SET"):]
    upd = upd[:upd.index('"""')]
    assert re.search(r"risk_class\s*=\s*\$\d", upd), "risk_class assignment vanished"
    assert "COALESCE(risk_class" not in upd, (
        "risk_class is now COALESCEd — re-read whether the exclusion above is "
        "still what protects the attribution, rather than leaving a guard that "
        "binds nothing"
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
