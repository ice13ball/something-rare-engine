# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The ISA contracts upsert froze the boundary and lied about the count.

Two defects in one statement, both found by check 25b on 2026-09-10.

1. `ON CONFLICT (isa_id) DO UPDATE SET` refreshed contractor_name,
   resource_type, act_date and expiry_date — and NOT `geom` or `area_km2`. ISA
   amends contract areas; that is the whole reason this is DO UPDATE rather
   than DO NOTHING. So the map kept whatever shape it saw first, forever.

2. The insert counter read `result == "INSERT 0 1"`, which an UPDATE reports
   too. Production evidence, and it is not subtle: the sync logged
   `records_added = 1817` against `total_records = 1318`. You cannot add 1,817
   rows to a table holding 1,318. Every amended contract counted as new, and
   the IndexNow ping gated on `inserted > 0` therefore fired every run.

⛔ Checked on the SQL text rather than by running the sync: the statement is
built once as a literal, and reaching it live needs an ArcGIS fetch of ISA
layer 32. The failure is a missing clause, which is exactly what a text check
catches — with a fixture assertion so an empty match cannot pass as clean.
"""
import pathlib
import re

SRC = (pathlib.Path(__file__).resolve().parents[1] / "domains" / "isa.py").read_text(encoding="utf-8")


def _contracts_upsert() -> str:
    m = re.search(r"INSERT INTO mining_contracts(.*?)\"\"\"", SRC, re.S)
    assert m, "fixture problem: the mining_contracts INSERT moved or was renamed"
    body = m.group(1)
    assert "ON CONFLICT" in body, (
        "fixture problem: matched a fragment with no ON CONFLICT — the regex "
        "is not capturing the statement this file is about"
    )
    return body


def test_a_republished_boundary_reaches_the_live_table():
    body = _contracts_upsert()
    set_clause = body.split("DO UPDATE", 1)[1]
    for col in ("geom", "area_km2"):
        assert re.search(rf"\b{col}\s*=", set_clause), (
            f"{col} is not refreshed on conflict, so an ISA amendment to a "
            "contract can never reach the map"
        )


def test_the_boundary_is_coalesced_not_blindly_overwritten():
    """⛔ A feature arriving without geometry must not erase what we hold."""
    body = _contracts_upsert()
    set_clause = body.split("DO UPDATE", 1)[1]
    assert "COALESCE(EXCLUDED.geom" in set_clause, (
        "geom is assigned unconditionally; one geometry-less feature from "
        "ArcGIS would blank a real contract boundary"
    )


def test_an_update_is_not_counted_as_an_insert():
    assert 'RETURNING (xmax = 0)' in _contracts_upsert(), (
        "without RETURNING (xmax = 0) there is nothing that can tell an insert "
        "from an update under DO UPDATE"
    )
    # ⛔ Strip comments before searching. The first version of this test read
    # the raw source and failed on the explanatory comment beside the fix,
    # which quotes the very pattern it forbids — a guard that reads prose is
    # not reading code.
    after = SRC.split("INSERT INTO mining_contracts", 1)[1]
    code_only = "\n".join(re.sub(r"#.*$", "", ln) for ln in after.splitlines())
    assert 'result == "INSERT 0 1"' not in code_only, (
        "the string check is back; an UPDATE reports 'INSERT 0 1' too, which "
        "is how records_added reached 1817 on a 1318-row table"
    )


def test_the_siblings_that_use_DO_NOTHING_still_may_count_by_string():
    """⛔ Scope guard. reserved_areas, apeis and relinquished_areas use
    DO NOTHING, where `result == "INSERT 0 1"` is CORRECT — a conflict returns
    'INSERT 0 0'. This test exists so a later cleanup does not 'fix' them into
    a more complicated form that buys nothing."""
    assert SRC.count("DO NOTHING") >= 3, (
        "fixture problem: the DO NOTHING siblings are gone, so this test is "
        "asserting something about code that no longer exists"
    )
