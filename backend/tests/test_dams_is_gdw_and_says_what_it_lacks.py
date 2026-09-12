# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The `dams` layer serves GDW v1.0, and must say what GDW does not have.

⚠️ THIS FILE REPLACES A GUARD THAT ASSERTED THE OPPOSITE. Earlier on 2026-09-11
`test_dams_is_goodd_not_gdw.py` existed to stop the loader claiming Global Dam
Watch, because the data was GOODD. Hours later the layer was deliberately moved
to GDW v1.0, so that guard now encoded a fact that had changed. A guard is not
sacred; the measurement behind it is. Both are recorded here so the flip reads
as a decision rather than as someone quietly deleting an inconvenient test.

WHAT CHANGED, measured on production 2026-09-11:

    before  GOODD 2019      38,667 points, 0 names, 0 attributes of any kind
    after   GDW v1.0        41,145 points, and:
              country     41,145  100%
              capacity    35,334   86%
              year        15,229   37%
              NAME        10,071   24.5%
              river        9,501   23%
              height       9,311   23%
              power_mw       242    0.6%

⛔ Three quarters of GDW's barriers are still unnamed. Swapping one false
impression ("these have names") for another ("now everything is known") would
be the same defect wearing a better dataset, so the locale checks below bind
the incompleteness, not just the name of the source.

⛔ GDW's no-data code is -99, on 40,903 power_mw values alone. The loader turns
it into SQL NULL. That rule is asserted against EXECUTABLE SQL, never against
the comment that explains it.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "backend" / "domains" / "land" / "extractive.py"


def _module() -> ast.Module:
    return ast.parse(INGEST.read_text())


def _sync_dams_body() -> str:
    """_sync_dams with its docstring removed — what the loader DOES."""
    tree = _module()
    for node in tree.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "_sync_dams":
            body = list(node.body)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body.pop(0)
            node.body = body or [ast.Pass()]
            return ast.unparse(node)
    raise AssertionError("_sync_dams is gone — re-anchor this guard")


def _gdw_insert_sql() -> str:
    """The mapping statement, read as a STRING CONSTANT, not as prose."""
    for node in _module().body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "_GDW_INSERT_SQL" in names and isinstance(node.value, ast.Constant):
                return str(node.value.value)
    raise AssertionError("_GDW_INSERT_SQL is gone — the -99 mapping lost its home")


def _mapping_lines() -> dict[str, str]:
    """Each mapped column -> the SQL line that produces it, comments stripped.

    ⛔ Per-COLUMN, not per-file. The first version of this guard asked whether
    the substring "> 0" appeared anywhere in the statement; it does, for several
    columns, so deleting the guard around dam_hgt_m left the test green. A
    sabotage that passes is a test that binds nothing.
    """
    out: dict[str, str] = {}
    for raw in _gdw_insert_sql().splitlines():
        line = raw.split("--", 1)[0].upper()      # a comment is not the mapping
        for col in ("DAM_HGT_M", "YEAR_DAM", "CAP_MCM", "AREA_SKM", "POWER_MW",
                    "DAM_NAME", "GRAND_ID"):
            if f"S.{col}" in line:
                out[col] = line
    return out


def test_the_loader_reads_only_the_gdw_barrier_layer():
    """⛔ GDW's archive also holds reservoir POLYGONS. This is a point layer."""
    body = _sync_dams_body()
    assert "gdw_barriers_staging" in body, "the loader no longer stages GDW"
    # the filename predicate itself, not merely the word appearing somewhere
    assert '"barrier" in fn.lower()' in body or "'barrier' in fn.lower()" in body, (
        "the shapefile chooser no longer filters for the barrier layer — it would "
        "pick up GDW_reservoirs_v1_0.shp, whose geometry is polygons"
    )


def test_the_no_data_code_is_mapped_to_null_in_executable_sql():
    """⛔ -99 is GDW's 'unknown'. Stored, it renders as a measurement."""
    lines = _mapping_lines()
    for col, guard in (("DAM_HGT_M", "> 0"), ("YEAR_DAM", "> 0"),
                       ("CAP_MCM", ">= 0"), ("AREA_SKM", ">= 0"), ("POWER_MW", "> -99")):
        assert col in lines, f"{col} is no longer mapped at all"
        line = lines[col]
        assert "CASE WHEN" in line and guard in line, (
            f"{col} is mapped as `{line.strip()}` — the `{guard}` guard is gone, so "
            f"GDW's -99 would be stored and shown as a real value"
        )
    # a name that is literally "None" is not a name
    assert "'NONE'" in lines.get("DAM_NAME", ""), \
        "the literal 'None' dam_name is no longer nulled out"


def test_catchment_area_is_never_written_into_the_volume_column():
    """volume_mcm means reservoir volume. CATCH_SKM is a catchment AREA."""
    sql = _gdw_insert_sql().upper()
    body = _sync_dams_body().upper()
    assert "CATCH_SKM" not in sql and "CATCH_SKM" not in body, (
        "CATCH_SKM (km²) is being written again into a column meaning million m³"
    )
    assert "CAP_MCM" in sql, "reservoir capacity stopped being loaded"


def test_the_licence_map_records_the_attribution_obligation():
    """⛔ GDW is CC BY, the GOODD it replaced was CC0. That is a new duty."""
    licences = (ROOT / "DATA-LICENCES.md").read_text()
    row = next((ln for ln in licences.splitlines() if "| `dams` |" in ln), "")
    assert row, "`dams` has no row in DATA-LICENCES.md"
    assert "GDW" in row, "the dams licence row does not name GDW"
    assert "CC BY 4.0" in row, (
        "the dams row lost GDW's CC BY terms — attribution is required and the "
        "platform must not quietly describe it as public domain"
    )
    assert "25988293" in row, "the row no longer cites where the terms were read"
    # the retired source stays visible rather than vanishing
    assert "retired 2026-09-11" in licences and "GOODD" in licences, \
        "GOODD was deleted from the licence map instead of being marked retired"


def test_every_locale_names_gdw_and_admits_what_is_missing():
    locales = sorted(p.name for p in (ROOT / "frontend" / "public" / "locales").iterdir() if p.is_dir())
    assert len(locales) >= 2, f"only {locales} discovered — re-anchor this guard"

    ROWS, NAMED = 41145, 10071
    def spellings(n: int) -> set[str]:
        base = f"{n:,}"
        return {base, base.replace(",", " "), base.replace(",", " "), base.replace(",", "."), str(n)}

    for loc in locales:
        entry = json.loads((ROOT / "frontend" / "public" / "locales" / loc / "legend.json").read_text())
        dams = entry["layers"].get("globalDams")
        assert dams, f"{loc}: the globalDams legend entry is gone"
        blob = " ".join(v for v in dams.values() if isinstance(v, str))

        assert "GDW" in blob, f"{loc}: the legend no longer names GDW"
        assert any(sp in blob for sp in spellings(ROWS)), \
            f"{loc}: the legend does not state the {ROWS:,} barriers actually loaded"
        # ⛔ the incompleteness is the part a reader is most likely to assume away
        assert any(sp in blob for sp in spellings(NAMED)), (
            f"{loc}: the legend does not say how many barriers are NAMED. GDW names "
            f"{NAMED:,} of {ROWS:,}; without that number the layer implies a complete register"
        )
