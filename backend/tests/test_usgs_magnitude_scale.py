# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A magnitude without its scale is a number USGS never published.

USGS states `magType` on every event, and the scales are not interchangeable.
Measured over the live M>=3 feed on 2026-09-10 (1,577 events):

    mb 1,048 · ml 328 · mww 96 · md 82 · mwr 11 · mw 7

The panel printed "M4.2". `status` was discarded too: 1,572 reviewed against 5
automatic in that window — rare, and exactly the case a reader wants flagged,
because an automatic solution is a machine's first guess.

⛔ This portal mirrors its sources 1:1, which forbids adding a fact the source
did not give as much as it forbids dropping one. "M" in front of a number that
USGS calls mb is our label, not theirs.
"""
import pathlib
import re

ROOT   = pathlib.Path(__file__).resolve().parents[2]
INGEST = ROOT / "backend" / "ingestion" / "usgs_earthquakes.py"
ONC    = ROOT / "backend" / "domains" / "onc.py"
SCHEMA = ROOT / "backend" / "schema" / "onc.py"
PANEL  = ROOT / "frontend" / "src" / "components" / "panels" / "ocean" / "OncPanel.tsx"

FIELDS = ("mag_type", "status")


def test_the_fixture_found_all_four_files():
    for f in (INGEST, ONC, SCHEMA, PANEL):
        assert f.is_file() and len(f.read_text(encoding="utf-8")) > 500, (
            f"fixture problem: {f} missing or too small to be real"
        )


def test_the_parser_reads_the_scale_and_the_review_state():
    src = INGEST.read_text(encoding="utf-8")
    assert 'props.get("magType")' in src, "the magnitude scale is not read"
    assert 'props.get("status")' in src, "the review state is not read"
    assert 'props.get("updated")' in src, "USGS's revision stamp is not read"


def test_the_table_can_hold_them_idempotently():
    ddl = SCHEMA.read_text(encoding="utf-8")
    for col in ("mag_type", "status", "usgs_updated_at"):
        assert re.search(rf"ADD COLUMN IF NOT EXISTS {col}\b", ddl), (
            f"{col} has no column, or is added without IF NOT EXISTS — the VPS "
            "re-runs the schema on every deploy"
        )


def test_the_upsert_writes_and_refreshes_them():
    src = ONC.read_text(encoding="utf-8")
    i = src.index("INSERT INTO usgs_earthquakes")
    stmt = src[i:src.index('"""', i)]
    for col in ("mag_type", "status", "usgs_updated_at"):
        assert col in stmt, f"the USGS insert does not write {col}"
        assert f"{col}=EXCLUDED.{col}" in stmt, (
            f"{col} is inserted but never refreshed, so a revised solution "
            "keeps the first values we ever saw"
        )


def test_the_endpoint_hands_the_scale_to_the_client():
    # Check 24d. A column nobody can read is a column nobody has.
    src = ONC.read_text(encoding="utf-8")
    i = src.index('@router.get("/v1/onc/earthquakes-near/')
    # ⚠️ End on the ASSIGNMENT, not on the bare cache lookup — the early
    # cache-hit return mentions _usgs_eq_cache[cache_key] several lines above
    # the SELECT, and slicing there searched a body with no query in it at all.
    body = src[i:src.index("_usgs_eq_cache[cache_key] = payload", i)]
    assert "SELECT usgs_id" in body, "fixture problem: the query is not in the slice"

    # ⛔ The SELECT and the response dict are checked SEPARATELY. Naming the
    # column in the response while the query never fetches it is precisely the
    # GEOTRACES defect — and a whole-body search stays green through it,
    # because the name is still present, just on the wrong side.
    query = body[body.index("SELECT usgs_id"):body.index('"""', body.index("SELECT usgs_id"))]
    resp  = body[body.index("result = ["):]
    for col in FIELDS:
        assert col in query, (
            f"the /v1/onc/earthquakes-near SELECT does not fetch {col}, so "
            "reading it from the row raises at runtime"
        )
        assert f'"{col}"' in resp, f"the response does not carry {col}"


def test_the_panel_labels_the_number_with_the_scale_usgs_gave():
    panel = PANEL.read_text(encoding="utf-8")
    assert "eq.mag_type" in panel, (
        'the panel still prints a bare "M" in front of every magnitude'
    )
    # ⛔ The bare-M literal must survive only as the fallback for an event that
    # genuinely carries no scale — never as the unconditional prefix.
    assert not re.search(r'>\s*M\{eq\.magnitude', panel), (
        "the magnitude is still prefixed with an unconditional M"
    )
    assert "automatic" in panel, (
        "an unreviewed automatic solution is displayed exactly like a "
        "human-reviewed one"
    )
