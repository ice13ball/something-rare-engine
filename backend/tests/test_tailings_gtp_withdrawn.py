# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Global Tailings Portal (GRID-Arendal) fields and Portal-only rows are
withheld pending written permission — decided 2026-09-23.

⛔ This is NOT a WDPA/KBA-style whole-layer withdrawal. `tailings` stays live:
9,837 `wapha` + 1,750 `grid-enriched` = 11,587 served facilities. Only the
361 `data_source='grid'` (Portal-only) rows are withheld, and only the
Portal-derived columns are hidden — including on `grid-enriched` rows, which
carry Portal data (mine_name, hazard_raw, owner_company, ...) even though a
WAPHA dam anchors them. See `domains/land/common.py` TAILINGS_SERVED_WHERE /
TAILINGS_PORTAL_COLUMNS, the single source of truth every surface applies.

The DB-backed tests below exercise REAL code paths against real PostGIS
(`get_tailings()`, the Area Export `_vector_rows()` builder) — not text greps.
Text-grep assertions are used only for surfaces too expensive to spin up a
full schema for (the overlap matview SQL, the public inventory, the SEO
layer-count query, i18n copy, the frontend filter UI and panel) — the same
"assert against the source" pattern `test_wdpa_withdrawn.py` uses for its own
equivalent surfaces.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
FRONTEND = REPO / "frontend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

pytestmark_db = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL"
)

# Every Portal-derived column, per domains/land/common.py. Duplicated here
# (not imported) so this test still catches a change to the wrong constant.
_PORTAL_COLUMNS = (
    "mine_name", "dam_type", "height_m", "volume_m3", "status",
    "owner_company", "operator", "construction_year", "raise_type",
    "hazard_raw", "grid_facility_id", "classification_system",
    "disclosure_link", "disclosure_origin", "history_stability_concerns",
    "downstream_impact", "recent_independent_expert_review",
    "extreme_weather_secure", "currently_approved_design",
    "closure_plan_dam", "closure_plan_long_term_monitoring",
    "internal_external_eng_support", "relevant_engineering_records",
    "disclosure_notes", "partners", "planned_storage_5_years",
)

_WAPHA_ID = 900001
_ENRICHED_ID = 900002
_GRID_ID = 900003


# ── DB-backed: real code paths against real PostGIS ─────────────────────────

@pytest.fixture
async def tailings_pool():
    import asyncpg
    import db
    from domains.land import extractive

    pool = await asyncpg.create_pool(os.environ["TEST_DATABASE_URL"])
    async with pool.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tailings_dams (
                id              INTEGER PRIMARY KEY,
                dam_name        TEXT,
                mine_name       TEXT,
                country         TEXT,
                dam_type        TEXT,
                height_m        DOUBLE PRECISION,
                volume_m3       DOUBLE PRECISION,
                risk_class      TEXT,
                status          TEXT,
                owner_company   TEXT,
                operator        TEXT,
                construction_year INTEGER,
                hazard_raw      TEXT,
                raise_type      TEXT,
                data_source     TEXT DEFAULT 'wapha',
                grid_facility_id TEXT,
                classification_system TEXT,
                disclosure_link TEXT,
                disclosure_origin TEXT,
                history_stability_concerns TEXT,
                downstream_impact TEXT,
                recent_independent_expert_review TEXT,
                extreme_weather_secure TEXT,
                currently_approved_design TEXT,
                closure_plan_dam TEXT,
                closure_plan_long_term_monitoring TEXT,
                internal_external_eng_support TEXT,
                relevant_engineering_records TEXT,
                disclosure_notes TEXT,
                partners TEXT,
                planned_storage_5_years DOUBLE PRECISION,
                geom            geometry(Point, 4326),
                geog            GEOGRAPHY(POINT, 4326) GENERATED ALWAYS AS (geom::geography) STORED,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("DELETE FROM tailings_dams WHERE id = ANY($1)",
                            [_WAPHA_ID, _ENRICHED_ID, _GRID_ID])
        await conn.execute("""
            INSERT INTO tailings_dams (id, dam_name, country, data_source, geom)
            VALUES ($1, 'TEST WAPHA Dam', 'Testland', 'wapha',
                    ST_SetSRID(ST_MakePoint(10.0, 20.0), 4326))
        """, _WAPHA_ID)
        await conn.execute("""
            INSERT INTO tailings_dams (
                id, dam_name, country, data_source, mine_name, dam_type,
                height_m, volume_m3, status, owner_company, operator,
                construction_year, hazard_raw, raise_type, grid_facility_id,
                classification_system, disclosure_link, disclosure_origin,
                history_stability_concerns, downstream_impact,
                recent_independent_expert_review, extreme_weather_secure,
                currently_approved_design, closure_plan_dam,
                closure_plan_long_term_monitoring, internal_external_eng_support,
                relevant_engineering_records, disclosure_notes, partners,
                planned_storage_5_years, geom
            ) VALUES (
                $1, 'TEST Enriched Dam', 'Testland', 'grid-enriched', 'TEST Mine',
                'upstream', 45, 1234567, 'Active', 'TEST Owner', 'TEST Operator',
                1990, 'Extreme', 'upstream', 'gtp-ubc-test-2',
                'ANCOLD 2012', 'https://tailing.grida.no/disclosures/TEST2',
                'Global Tailings Portal', 'No', 'Yes', '2018', 'Yes', 'Yes',
                'Yes', 'Yes', 'Both', 'Yes', 'TEST disclosure notes', 'TEST Partner',
                2000000, ST_SetSRID(ST_MakePoint(11.0, 21.0), 4326)
            )
        """, _ENRICHED_ID)
        await conn.execute("""
            INSERT INTO tailings_dams (
                id, dam_name, country, data_source, mine_name, hazard_raw,
                owner_company, grid_facility_id, geom
            ) VALUES (
                $1, 'TEST Portal-Only Dam', 'Testland', 'grid', 'TEST Mine 3',
                'High', 'TEST Owner 3', 'gtp-ubc-test-3',
                ST_SetSRID(ST_MakePoint(12.0, 22.0), 4326)
            )
        """, _GRID_ID)

    original_pool = db.pool
    db.pool = pool
    extractive.clear_caches()
    try:
        yield extractive
    finally:
        extractive.clear_caches()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM tailings_dams WHERE id = ANY($1)",
                                [_WAPHA_ID, _ENRICHED_ID, _GRID_ID])
        db.pool = original_pool
        await pool.close()


@pytest.fixture
async def full_schema(tailings_pool):
    """Extends `tailings_pool` with the REAL full schema (`schema.ensure_schema()`
    + `ensure_land_schema()`) so cross-table endpoints — the public inventory,
    the SEO layer-count query, the overlap matview — can be exercised through
    the actual code paths instead of a source-text grep. Additive only
    (every statement is `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`), so it
    never disturbs the three rows `tailings_pool` already seeded.
    """
    import schema
    from domains.land.schema_orchestrator import ensure_land_schema

    await schema.ensure_schema()
    await ensure_land_schema()
    yield tailings_pool


def _assert_no_portal_leak(props: dict, *, surface: str):
    for col in _PORTAL_COLUMNS:
        assert props.get(col) is None, (
            f"{surface}: Portal-derived column {col!r} leaked a non-null value "
            f"({props.get(col)!r}) — withdrawn 2026-09-23, pending permission"
        )


@pytest.mark.asyncio
@pytestmark_db
async def test_served_where_excludes_only_the_grid_only_row(tailings_pool):
    """The SQL predicate every surface must reuse."""
    import db
    from domains.land.common import TAILINGS_SERVED_WHERE

    async with db.pool.acquire() as conn:
        ids = await conn.fetch(
            f"SELECT id FROM tailings_dams WHERE id = ANY($1) AND {TAILINGS_SERVED_WHERE}",
            [_WAPHA_ID, _ENRICHED_ID, _GRID_ID],
        )
    served = {r["id"] for r in ids}
    assert served == {_WAPHA_ID, _ENRICHED_ID}


@pytest.mark.asyncio
@pytestmark_db
async def test_get_tailings_geojson_excludes_grid_rows_and_portal_fields(tailings_pool):
    extractive = tailings_pool
    response = await extractive.get_tailings()
    fc = json.loads(response.body)
    ids = {f["properties"]["id"] for f in fc["features"]}

    assert _GRID_ID not in ids, "Portal-only facility (data_source='grid') was served"
    assert {_WAPHA_ID, _ENRICHED_ID}.issubset(ids)

    for f in fc["features"]:
        if f["properties"]["id"] not in (_WAPHA_ID, _ENRICHED_ID):
            continue
        _assert_no_portal_leak(f["properties"], surface="get_tailings() GeoJSON")
        # WAPHA-origin fields must still be there — this is a field cut, not a
        # blackout.
        assert f["properties"]["dam_name"]
        assert f["properties"]["country"] == "Testland"
        assert f["properties"]["data_source"] in ("wapha", "grid-enriched")


@pytest.mark.asyncio
@pytestmark_db
async def test_area_export_excludes_grid_rows_and_portal_fields(tailings_pool):
    from services.export_query import Aoi
    from services.export_registry import EXPORT_LAYERS
    from routers.export import _vector_rows

    entry = EXPORT_LAYERS["tailings"]
    assert not set(entry.fields) & set(_PORTAL_COLUMNS), (
        "the export field tuple names a Portal-derived column directly"
    )
    aoi = Aoi(kind="bbox", bbox=(9.0, 19.0, 13.0, 23.0))
    rows, _capped = await _vector_rows(entry, aoi)
    ids = {r["id"] for r in rows}

    assert _GRID_ID not in ids, "Area Export served the Portal-only facility"
    assert {_WAPHA_ID, _ENRICHED_ID}.issubset(ids)
    for r in rows:
        if r["id"] not in (_WAPHA_ID, _ENRICHED_ID):
            continue
        _assert_no_portal_leak(r, surface="Area Export")


# ── Source-level: surfaces too expensive to stand a full schema up for ──────

@pytest.mark.asyncio
@pytestmark_db
async def test_overlap_matview_drops_portal_columns_and_grid_rows(full_schema):
    """Builds `overlap_tailings_landslides` through the real
    `land_overlaps.ensure_overlap_views()` / `refresh_overlap_views()`, against
    one seeded landslide near the WAPHA dam and one near the Portal-only
    (`data_source='grid'`) dam."""
    import db
    import land_overlaps

    landslide_ids = [9990001, 9990002]
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM landslides WHERE id = ANY($1)", landslide_ids)
        await conn.execute("""
            INSERT INTO landslides (id, event_date, event_type, country, geom)
            VALUES
                ($1, '2026-01-01', 'mudslide', 'Testland',
                    ST_SetSRID(ST_MakePoint(10.01, 20.01), 4326)),
                ($2, '2026-01-02', 'rockfall', 'Testland',
                    ST_SetSRID(ST_MakePoint(12.01, 22.01), 4326))
        """, *landslide_ids)
    try:
        await land_overlaps.ensure_overlap_views()
        await land_overlaps.refresh_overlap_views()

        async with db.pool.acquire() as conn:
            # ⚠️ `information_schema.columns` does NOT list materialized-view
            # columns (relkind 'm' is outside the SQL-standard view it models —
            # verified live: it silently returns zero rows here, which would
            # have made this assertion vacuously true against real sabotage).
            # `pg_attribute` sees every column of every relation kind.
            cols = {
                r["attname"] for r in await conn.fetch(
                    "SELECT attname FROM pg_attribute "
                    "WHERE attrelid = 'overlap_tailings_landslides'::regclass "
                    "AND attnum > 0 AND NOT attisdropped"
                )
            }
            rows = await conn.fetch(
                "SELECT tailings_id FROM overlap_tailings_landslides "
                "WHERE landslide_id = ANY($1)",
                landslide_ids,
            )
        for col in ("hazard_raw", "classification_system", "mine_name"):
            assert col not in cols, f"overlap_tailings_landslides still selects {col}"

        ids = {r["tailings_id"] for r in rows}
        assert _GRID_ID not in ids, (
            "overlap_tailings_landslides served the Portal-only "
            "(data_source='grid') facility"
        )
        assert _WAPHA_ID in ids, (
            "overlap_tailings_landslides lost the WAPHA row near a seeded landslide"
        )
    finally:
        async with db.pool.acquire() as conn:
            await conn.execute("DELETE FROM landslides WHERE id = ANY($1)", landslide_ids)


@pytest.mark.asyncio
@pytestmark_db
async def test_public_inventory_credits_wapha_and_counts_served_rows_only(full_schema):
    """Calls the real `/v1/stats/dataset-counts` coroutine — not a source grep."""
    import db
    import main
    from domains.land.common import TAILINGS_SERVED_WHERE

    original_pool = main._pool
    main._pool = db.pool
    main._dataset_counts_cache = None
    main._dataset_counts_cache_at = 0.0
    try:
        result = await main.get_dataset_counts()
    finally:
        main._dataset_counts_cache = None
        main._dataset_counts_cache_at = 0.0
        main._pool = original_pool

    item = next(
        i for g in result["groups"] for i in g["items"] if i["key"] == "tailings"
    )
    assert "GRID-Arendal" not in item["source_org"], (
        "inventory attribution still names GRID-Arendal as the source"
    )
    assert "WAPHA" in item["source_org"] or "Hudson-Edwards" in item["source_org"]

    async with db.pool.acquire() as conn:
        served = await conn.fetchval(
            f"SELECT count(*) FROM tailings_dams WHERE {TAILINGS_SERVED_WHERE}"
        )
        total = await conn.fetchval("SELECT count(*) FROM tailings_dams")
    assert item["count"] == served, (
        "the public dataset-counts query does not apply TAILINGS_SERVED_WHERE"
    )
    assert total > served, (
        "test premise stale — the seeded grid-only row is no longer in the table"
    )


@pytest.mark.asyncio
@pytestmark_db
async def test_seo_layer_count_excludes_grid_rows(full_schema):
    """Calls the real `seo_sitemap_core()` coroutine that feeds /layer/tailings."""
    import db
    from domains.land.common import TAILINGS_SERVED_WHERE
    from domains.seo import seo_sitemap_core

    result = await seo_sitemap_core()

    async with db.pool.acquire() as conn:
        served = await conn.fetchval(
            f"SELECT count(*) FROM tailings_dams WHERE {TAILINGS_SERVED_WHERE}"
        )
        total = await conn.fetchval("SELECT count(*) FROM tailings_dams")
    assert result["layer_counts"]["tailings"] == served, (
        "the /layer/tailings SEO page count still counts every row"
    )
    assert total > served, (
        "test premise stale — the seeded grid-only row is no longer in the table"
    )


def test_export_registry_provenance_names_the_withdrawal():
    from services.export_registry import EXPORT_LAYERS

    entry = EXPORT_LAYERS["tailings"]
    assert entry.extra_where and "grid" in entry.extra_where
    assert "withdrawn" in entry.prov.note.lower()
    assert "CC0" in (entry.prov.license or "")


@pytest.mark.asyncio
@pytestmark_db
async def test_the_gtp_sync_is_gated_and_still_names_its_upstream(tailings_pool, monkeypatch):
    """Mirrors `test_a_source_that_fetches_from_the_network_is_never_marked_static`
    in test_cadence.py — that test proves the cadence entry is honest about
    fetching a live upstream. This one proves the fetch itself is gated: calls
    the real coroutine with the network patched to FAIL the test on any
    request, and asserts no row changed and a sync_log skip trace was written.
    """
    import db
    from domains.land import extractive

    assert extractive.TAILINGS_GTP_WITHDRAWN is True, (
        "test premise stale — the withdrawal flag was flipped back on"
    )

    def _fail_on_network(*_a, **_kw):
        raise AssertionError(
            "_enrich_tailings_from_grid made a network call while "
            "TAILINGS_GTP_WITHDRAWN is True"
        )

    monkeypatch.setattr(extractive.httpx, "AsyncClient", _fail_on_network)

    async with db.pool.acquire() as conn:
        before = {
            r["id"]: dict(r) for r in await conn.fetch(
                "SELECT * FROM tailings_dams WHERE id = ANY($1)",
                [_WAPHA_ID, _ENRICHED_ID, _GRID_ID],
            )
        }
        await conn.execute("DELETE FROM sync_log WHERE source = $1", "tailings_enrich")

    added = await extractive._enrich_tailings_from_grid(force=True)
    assert added == 0

    async with db.pool.acquire() as conn:
        after = {
            r["id"]: dict(r) for r in await conn.fetch(
                "SELECT * FROM tailings_dams WHERE id = ANY($1)",
                [_WAPHA_ID, _ENRICHED_ID, _GRID_ID],
            )
        }
        log_row = await conn.fetchrow(
            "SELECT skipped_reason, skipped_at FROM sync_log WHERE source = $1",
            "tailings_enrich",
        )
    assert after == before, "the withdrawn sync changed a tailings_dams row"
    assert log_row is not None, (
        "the gated branch wrote no sync_log trace — every early return in a "
        "sync needs one (CLAUDE.md engine rule)"
    )
    assert log_row["skipped_at"] is not None
    assert log_row["skipped_reason"] and "withdraw" in log_row["skipped_reason"].lower(), (
        f"skipped_reason does not name the withdrawal: {log_row['skipped_reason']!r}"
    )


def test_no_public_surface_still_claims_a_hazard_rating_count():
    """Failure mode 3: a filter, legend or count still built on Portal fields."""
    surfaces = {
        "server.js": FRONTEND / "server.js",
        "legalContent.ts": FRONTEND / "src" / "content" / "legalContent.ts",
        "index.html": FRONTEND / "index.html",
        "exportLayers.ts": FRONTEND / "src" / "utils" / "exportLayers.ts",
        "landLayers.ts": FRONTEND / "src" / "types" / "landLayers.ts",
    }
    banned = ("1,900+", "~2,100", "2,100 facilities", "11,900+", "1,800+", "222 mining companies")
    for name, path in surfaces.items():
        text = path.read_text()
        for phrase in banned:
            assert phrase not in text, f"{name} still carries the withdrawn-field claim {phrase!r}"


def test_legend_locales_credit_wapha_and_state_the_withdrawal():
    for locale in ("en", "pl", "de", "fr"):
        path = FRONTEND / "public" / "locales" / locale / "legend.json"
        d = json.loads(path.read_text(encoding="utf-8"))
        entry = d["layers"]["tailingsDams"]
        blob = json.dumps(entry, ensure_ascii=False)
        assert "dryad.j3tx95xmg" in blob, f"{locale}: WAPHA/Dryad citation missing"
        assert re.search(r"grid-arendal", blob, re.IGNORECASE), (
            f"{locale}: no mention of GRID-Arendal (should explain the withdrawal)"
        )
        assert re.search(r"withdraw|wycof|zurückgezog|retir", blob, re.IGNORECASE), (
            f"{locale}: legend text does not say the Portal fields are withdrawn"
        )
        assert "2,100" not in blob and "2 100" not in blob and "2.100" not in blob, (
            f"{locale}: still quotes the withdrawn ~2,100-dams-rated figure"
        )


def test_hazards_section_no_longer_builds_a_filter_on_portal_fields():
    src = (FRONTEND / "src" / "components" / "controls" / "sections"
           / "HazardsMonitoringSection.tsx").read_text()
    tailings_block = src[src.index('id="tailings"'):src.index('id="fires"')]
    assert "filterContent" not in tailings_block, (
        "tailings LayerRow still renders a filter facet — built on hazard_raw/"
        "status, both Global Tailings Portal fields withdrawn 2026-09-23"
    )
    assert "TAILINGS_RISK_FILTER_DEFS" not in src

# test_tailings_panel_never_reads_a_portal_field moved to a real render test:
# frontend/src/__tests__/tailings-panel-gtp-withdrawn.test.tsx — a source grep
# for `p.hazard_raw` cannot tell "never read" from "read but not rendered",
# and cannot catch the field reaching the DOM through a spread or a helper.
