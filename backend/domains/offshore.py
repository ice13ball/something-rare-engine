# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Offshore activity registries — 26 national regulators plus shared helpers.

Feeds the `offshore_activities` table. The read path is MVT tiles served by
backend/routers/spatial_v2.py, so this module has no endpoints of its own.

The table is DELIBERATELY multi-type: every consumer must filter
`activity_type`.

Moved verbatim out of backend/main.py (Task 6 of the backend vertical-split
refactor). Only permitted edits applied: `_pool.acquire()` -> `db.pool.acquire()`
/ `_db.pool` -> `db.pool` (same pattern established in Tasks 3/4/5, since this
module cannot import main's `_pool` global without recreating the import cycle
this refactor removes), leading underscore dropped from the 26 sync function
names and the 5 shared helpers (`offshore_upsert`, `offshore_tag_sovereign`,
`clear_offshore_tile_cache`, `fetch_arcgis_features_url`, `fetch_arcgis_no_ssl`
— all verified offshore-only by mapping every reference to its enclosing
top-level function before moving), and imports/docstring.

`_sync_all_sources` (the weekly cross-domain orchestrator) and
`_sync_arcgis_group` (ISA reserved/apeis/relinquished/contracts) were matched
by an earlier regex-based function count but call zero offshore functions —
verified by reading their bodies, not just their names. `_sync_all_sources`
stays in main.py; `_sync_arcgis_group` has since moved to `domains/isa.py` as
`isa.sync_arcgis_group` (Phase 4).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from urllib.parse import urlparse

import db
import httpx
from parse_util import coerce_date as _coerce_date
from sync_log import log_sync as _log_sync, log_sync_skipped as _log_sync_skipped

log = logging.getLogger(__name__)


# ── Offshore Activities sync helpers ─────────────────────────────────────────


async def offshore_upsert(conn, rows: list[dict]) -> int:
    """Bulk-upsert offshore_activities rows. Each row must contain keys matching
    the table columns. Returns the number of newly inserted rows."""
    inserted = 0
    for r in rows:
        geom_json = json.dumps(r["geom"]) if isinstance(r["geom"], dict) else r["geom"]
        result = await conn.execute(
            """INSERT INTO offshore_activities
                   (source, source_id, activity_type, name, operator, country,
                    status, awarded_date, expires_date, portal_url, attributes, geom)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,
                       -- ST_MakeValid: upstream registries ship self-intersecting
                       -- rings / nested shells (22 found 2026-06: NSTA, EMODnet,
                       -- Sodir, NOPTA…). Invalid geoms render zoom/tile-dependently
                       -- in the MVT pipeline (partial or missing claims).
                       -- CollectionExtract(…,3) keeps only polygonal parts.
                       ST_Multi(ST_CollectionExtract(ST_MakeValid(
                           ST_SetSRID(ST_GeomFromGeoJSON($12), 4326)), 3)))
               ON CONFLICT (source, source_id) DO UPDATE SET
                   activity_type = EXCLUDED.activity_type,
                   name          = EXCLUDED.name,
                   operator      = EXCLUDED.operator,
                   country       = EXCLUDED.country,
                   status        = EXCLUDED.status,
                   awarded_date  = EXCLUDED.awarded_date,
                   expires_date  = EXCLUDED.expires_date,
                   portal_url    = EXCLUDED.portal_url,
                   attributes    = EXCLUDED.attributes,
                   geom          = EXCLUDED.geom,
                   updated_at    = NOW()""",
            r["source"], r["source_id"], r["activity_type"],
            r.get("name"), r.get("operator"), r.get("country"),
            r.get("status"), _coerce_date(r.get("awarded_date")), _coerce_date(r.get("expires_date")),
            r.get("portal_url"), json.dumps(r.get("attributes") or {}),
            geom_json,
        )
        if result == "INSERT 0 1":
            inserted += 1
    return inserted


async def offshore_tag_sovereign(conn, source: str):
    """Backfill sovereign + jurisdiction for rows just inserted from `source`."""
    await conn.execute(
        """UPDATE offshore_activities oa
           SET sovereign   = mb.sovereign1,
               jurisdiction = CASE
                   WHEN ST_Within(oa.geom, mb.geom) THEN 'eez'
                   WHEN ST_Intersects(oa.geom, mb.geom) THEN 'overlap'
                   ELSE NULL END
           FROM maritime_boundaries mb
           WHERE ST_Intersects(oa.geom, mb.geom)
             AND oa.source = $1""",
        source,
    )


def clear_offshore_tile_cache():
    from routers import spatial_v2 as _sv2
    import offshore_tile_baker as _baker
    # Clear only the on-demand (filtered) raster cache; the pre-baked pyramid
    # is rebuilt by the baker — don't wipe _baked/ here.
    import shutil as _shutil
    ondemand = _sv2._RASTER_CACHE_DIR / "offshore-activities" / "_ondemand"
    _shutil.rmtree(ondemand, ignore_errors=True)
    _sv2._RASTER_MEM.clear()
    if db.pool is not None:
        asyncio.create_task(_baker.schedule_bake(db.pool))


def clear_caches() -> None:
    """No response caches in this module — the read path is MVT tiles served by
    routers/spatial_v2.py with its own disk cache. Present so the domain honours
    the uniform contract in domains/__init__.py."""
    return


async def fetch_arcgis_features_url(url: str, out_fields: str = "*", extra_params: dict | None = None) -> list[dict]:
    """Paginated fetch from an arbitrary ArcGIS FeatureServer/MapServer query URL."""
    all_features: list[dict] = []
    offset = 0
    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            params = {
                "where": "1=1",
                "outFields": out_fields,
                "f": "geojson",
                "resultRecordCount": 1000,
                "resultOffset": offset,
                **(extra_params or {}),
            }
            r = await _get_with_retry(client, url, params=params, label="arcgis page")
            features = r.json().get("features", [])
            all_features.extend(features)
            if len(features) < 1000:
                break
            offset += 1000
    return all_features


async def _get_with_retry(client, url, *, params=None, label="", attempts=3):
    """One GET, retried on transport failure and on 5xx.

    ⛔ `grep -cE 'retry|backoff|tenacity' offshore.py` returned ZERO across a
    file holding 26 sync functions, every one talking to a government ArcGIS or
    WFS endpoint. A single transient failure on an opening fetch aborted that
    source's whole sync — check 25e, the same shape as the ArgoVis vocabulary
    call, the MOSAIC seed fetch and the MEMENTO login, all found the same week.

    ⛔ A 4xx is NOT retried. A 404 or a 400 is the server saying the layer moved
    or the query is wrong; repeating it cannot change the answer and only
    hammers a public registry. Only 5xx and transport errors earn another try.

    Raises the last error on exhaustion — "this source is unreachable" and
    "this source has nothing" must not share a code path.
    """
    last = None
    for attempt in range(attempts):
        try:
            resp = await client.get(url, params=params)
            if resp.status_code < 500:
                resp.raise_for_status()    # 4xx raises here and is not retried
                return resp
            last = httpx.HTTPStatusError(
                f"HTTP {resp.status_code}", request=resp.request, response=resp)
            log.warning("offshore: %s -> HTTP %s (attempt %d/%d)",
                        label or url, resp.status_code, attempt + 1, attempts)
        except httpx.HTTPStatusError:
            raise                          # deliberate: see above
        except Exception as exc:
            last = exc
            log.warning("offshore: %s -> %s (attempt %d/%d)",
                        label or url, type(exc).__name__, attempt + 1, attempts)
        if attempt + 1 < attempts:
            await asyncio.sleep(2 * (attempt + 1))
    raise last if last else RuntimeError(f"offshore: {label or url} failed")


# ── Phase 2: EMODnet Human Activities ────────────────────────────────────────

async def sync_emodnet_offshore() -> int:
    """Fetch oil/gas licences and wind farm polygons from EMODnet WFS."""
    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = 'offshore_activities'"
        )
        if last and (datetime.now(tz=timezone.utc) - last).days < 7:
            log.info("emodnet-offshore: skipping — synced %s", last.date())
            return 0

    WFS_BASE = "https://ows.emodnet-humanactivities.eu/wfs?service=WFS&version=1.1.0&request=GetFeature&outputFormat=application/json"
    # Canonical type names verified via GetCapabilities 2026-04-25
    type_map = [
        ("emodnet:activelicenses", "oil_gas"),
        ("emodnet:windfarmspoly", "offshore_wind"),
    ]

    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=120) as client:
        for type_name, activity_type in type_map:
            url = f"{WFS_BASE}&typeName={type_name}"
            try:
                r = await _get_with_retry(client, url, label=f"emodnet {type_name}")
                data = r.json()
            except Exception as exc:
                log.warning("emodnet-offshore %s: fetch failed — %s", type_name, exc)
                continue
            features = data.get("features") or []
            for f in features:
                props = f.get("properties") or {}
                geom = f.get("geometry")
                if not geom:
                    continue
                rows.append({
                    "source": "emodnet",
                    "source_id": str(f.get("id") or props.get("code") or ""),
                    "activity_type": activity_type,
                    "name": props.get("name") or props.get("NAME"),
                    "operator": props.get("operator") or props.get("company"),
                    "country": props.get("country"),
                    "status": (props.get("status") or props.get("type") or "active").lower(),
                    # validfrom/validto like "2009-07-29Z"; strip Z; None if absent or null
                    "awarded_date": (props.get("validfrom") or "").rstrip("Z") or None,
                    "expires_date": (props.get("validto") or "").rstrip("Z") or None,
                    "portal_url": "https://www.emodnet-humanactivities.eu/view-data.php",
                    "attributes": props,
                    "geom": geom,
                })

    if not rows:
        log.warning("emodnet-offshore: no features returned")
        await _log_sync_skipped("offshore_activities", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "emodnet")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("offshore_activities", inserted, total)
    log.info("emodnet-offshore: %d new / %d total", inserted, total)
    return inserted


# ── Phase 3: BOEM (USA) ──────────────────────────────────────────────────────

async def sync_boem_offshore() -> int:
    """Fetch BOEM oil/gas leases (4 OCS regions) + wind leases via MarineCadastre."""
    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = 'boem-offshore'"
        )
    if last and (datetime.now(tz=timezone.utc) - last).days < 7:
        log.info("boem-offshore: skipping — synced %s", last.date())
        return 0

    async def _resolve_layer(base: str, layer_name: str) -> str | None:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await _get_with_retry(client, f"{base}?f=json", label="arcgis layer index")
            for L in r.json().get("layers", []):
                if L.get("name") == layer_name:
                    return f"{base}/{L['id']}/query"
        return None

    rows: list[dict] = []
    REGIONS = [
        ("https://gis.boem.gov/arcgis/rest/services/BOEM_BSEE/GOA_Layers/MapServer", "Gulf of America"),
        ("https://gis.boem.gov/arcgis/rest/services/BOEM_BSEE/POC_Layers/MapServer", "Pacific"),
        ("https://gis.boem.gov/arcgis/rest/services/BOEM_BSEE/ATL_Layers/MapServer", "Atlantic"),
        ("https://gis.boem.gov/arcgis/rest/services/BOEM_BSEE/AK_Layers/MapServer",  "Alaska"),
    ]
    INACTIVE = {"TERM", "CANC", "EXPR", "RELQ"}

    for base, region in REGIONS:
        try:
            url = await _resolve_layer(base, "BOEM Oil and Gas Leases")
            if not url:
                log.warning("boem-offshore %s: no 'Oil and Gas Leases' layer found", region)
                continue
            features = await fetch_arcgis_features_url(url)
        except Exception as exc:
            log.warning("boem-offshore %s: fetch failed — %s", region, exc)
            continue
        region_rows = 0
        for f in features:
            props = f.get("properties") or {}
            geom  = f.get("geometry")
            lease = props.get("LEASE_NUMBER")
            status = (props.get("LEASE_STATUS_CD") or "").strip().upper()
            if not lease or not geom or status in INACTIVE:
                continue
            rows.append({
                "source": "boem",
                "source_id": f"{region}:{lease}",
                "activity_type": "oil_gas",
                "name": lease,
                "operator": None,
                "country": "United States",
                "status": status.lower() or "active",
                "awarded_date": _coerce_date(props.get("LEASE_EFF_DATE")),
                "expires_date": _coerce_date(props.get("LEASE_EXPIR_DATE")),
                "portal_url": f"https://www.data.bsee.gov/Leasing/Leases/Default.aspx?LeaseNumber={lease}",
                "attributes": props,
                "geom": geom,
            })
            region_rows += 1
        log.info("boem-offshore %s: %d active leases", region, region_rows)

    # Wind via MarineCadastre (best-effort; tolerate failure without aborting oil/gas)
    WIND_BASE = (
        "https://services2.coastalscience.noaa.gov/arcgis/rest/services/"
        "MarineCadastre/OffshoreLeases/MapServer"
    )
    try:
        wind_url = await _resolve_layer(WIND_BASE, "BOEM Wind Lease Areas")
        if wind_url:
            for f in await fetch_arcgis_features_url(wind_url):
                props = f.get("properties") or {}
                geom  = f.get("geometry")
                if not geom:
                    continue
                lease = props.get("LEASE_NUMBER") or props.get("LEASE_NUM") or props.get("OBJECTID")
                rows.append({
                    "source": "boem",
                    "source_id": f"wind:{lease}",
                    "activity_type": "offshore_wind",
                    "name": props.get("LEASE_NUMBER") or props.get("LEASE_NAME"),
                    "operator": props.get("COMPANY") or props.get("LESSEE"),
                    "country": "United States",
                    "status": (props.get("STATUS") or "active").lower(),
                    "awarded_date": _coerce_date(props.get("LEASE_EFF_DATE") or props.get("EFFECTIVE_DATE")),
                    "expires_date": _coerce_date(props.get("LEASE_EXP_DATE") or props.get("EXPIRATION_DATE")),
                    "portal_url": "https://www.boem.gov/renewable-energy/lease-and-grant-information",
                    "attributes": props,
                    "geom": geom,
                })
        else:
            log.warning("boem-offshore wind: 'BOEM Wind Lease Areas' layer not found in MarineCadastre")
    except Exception as exc:
        log.warning("boem-offshore wind: fetch failed — %s", exc)

    if not rows:
        log.warning("boem-offshore: no features returned from any region")
        await _log_sync_skipped("boem-offshore", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "boem")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("boem-offshore", inserted, total)
    log.info("boem-offshore: %d new / %d total", inserted, total)
    return inserted


# ── Phase 5: Crown Estate (UK) ───────────────────────────────────────────────

async def sync_crown_estate_wind() -> int:
    """Fetch UK offshore wind lease areas from The Crown Estate open data (England, Wales, NI).

    Source: WindSite_EngWalNI_TheCrownEstate ArcGIS FeatureServer.
    Fields: Name_Prop (project name), Name_Ten (lessee/operator), Wind_Round,
            Lease_Stat, Inf_Status (operational status), km2.
    Scotland is managed by Crown Estate Scotland — separate dataset not included here.
    """
    CE_URL = (
        "https://services2.arcgis.com/PZklK9Q45mfMFuZs/arcgis/rest/services/"
        "WindSite_EngWalNI_TheCrownEstate/FeatureServer/0/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(CE_URL, out_fields="*")
    except Exception as exc:
        log.warning("crown-estate-wind: fetch failed — %s", exc)
        await _log_sync_skipped("crown_estate", f"fetch failed: {type(exc).__name__}")
        return 0

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        inf_status = (props.get("Inf_Status") or "").lower()
        rows.append({
            "source": "crown_estate",
            "source_id": str(props.get("OBJECTID") or ""),
            "activity_type": "offshore_wind",
            "name": props.get("Name_Prop"),
            "operator": props.get("Name_Ten"),
            "country": "GBR",
            "status": inf_status or "active",
            "awarded_date": None,
            "expires_date": None,
            "portal_url": props.get("ODP_Hyperlink") or "https://www.thecrownestate.co.uk/energy-minerals-and-infrastructure/offshore-wind",
            "attributes": {k: v for k, v in props.items()},
            "geom": geom,
        })

    if not rows:
        log.warning("crown-estate-wind: no features returned")
        await _log_sync_skipped("crown_estate", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "crown_estate")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("crown_estate", inserted, total)
    log.info("crown-estate-wind: %d new / %d total", inserted, total)
    return inserted


# ── Phase 5: NOPTA (Australia) ───────────────────────────────────────────────

async def sync_nopta_petroleum() -> int:
    """Fetch Australian offshore petroleum titles from NOPTA ArcGIS server.

    Source: arcgis.nopta.gov.au TitlesCompany_NOPTA MapServer layer 0.
    Fields: Title (permit number), TitleType, Status, TitleOprat (operator),
            TitleHold (titleholder), GrantDate/ExpiryDate (Unix ms epoch).
    All 248 features are offshore by definition (NOPTA is the National Offshore
    Petroleum Titles Administrator).
    """
    NOPTA_URL = (
        "https://arcgis.nopta.gov.au/arcgis/rest/services/Public/"
        "TitlesCompany_NOPTA/MapServer/0/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(NOPTA_URL, out_fields="*")
    except Exception as exc:
        log.warning("nopta-petroleum: fetch failed — %s", exc)
        await _log_sync_skipped("nopta", f"fetch failed: {type(exc).__name__}")
        return 0

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        title_type = (props.get("TitleType") or "").lower()
        activity_type = "oil_gas"  # NOPTA only covers petroleum / GHG storage
        def _ms_to_date(ms):
            if ms is None:
                return None
            try:
                return datetime.utcfromtimestamp(int(ms) / 1000).date().isoformat()
            except Exception:
                return None
        rows.append({
            "source": "nopta",
            "source_id": str(props.get("Title") or props.get("OBJECTID") or ""),
            "activity_type": activity_type,
            "name": props.get("Title"),
            "operator": props.get("TitleOprat") or props.get("TitleHold"),
            "country": "AUS",
            "status": (props.get("Status") or "active").lower(),
            "awarded_date": _ms_to_date(props.get("GrantDate")),
            "expires_date": _ms_to_date(props.get("ExpiryDate")),
            "portal_url": "https://www.nopta.gov.au/titles-register.html",
            "attributes": {k: v for k, v in props.items()},
            "geom": geom,
        })

    if not rows:
        log.warning("nopta-petroleum: no features returned")
        await _log_sync_skipped("nopta", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "nopta")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    log.info("nopta-petroleum: %d new / %d total", inserted, total)
    await _log_sync("nopta", inserted, len(rows))
    return inserted


# ── Phase 5: NZP&M (New Zealand) ─────────────────────────────────────────────

async def sync_nzpam_offshore() -> int:
    """Fetch NZ offshore petroleum permits from NZP&M ArcGIS Online.

    Source: services3.arcgis.com Petroleum_and_minerals FeatureServer layer 23
    (Petroleum Active Permits), filtered to PERMIT_OFFSHORE_ONSHORE='Offshore'.
    Fields: Number (permit no), TypeCode (licence type), Status, Operator, Owner,
            Granted/Expiry (Unix ms epoch), Location (basin).
    """
    NZPAM_URL = (
        "https://services3.arcgis.com/fp1tibNcN9mbExhG/arcgis/rest/services/"
        "Petroleum_and_minerals/FeatureServer/23/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(
            NZPAM_URL,
            out_fields="*",
            extra_params={"where": "PERMIT_OFFSHORE_ONSHORE='Offshore'"},
        )
    except Exception as exc:
        log.warning("nzpam-offshore: fetch failed — %s", exc)
        await _log_sync_skipped("nzpam", f"fetch failed: {type(exc).__name__}")
        return 0

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        permit_type = (props.get("TypeCode") or "").lower()
        activity_type = "seabed_mining" if "mining" in permit_type else "oil_gas"
        def _ms_to_date(ms):
            if ms is None:
                return None
            try:
                return datetime.utcfromtimestamp(int(ms) / 1000).date().isoformat()
            except Exception:
                return None
        rows.append({
            "source": "nzpam",
            "source_id": str(props.get("Number") or props.get("OBJECTID") or ""),
            "activity_type": activity_type,
            "name": str(props.get("Number")) if props.get("Number") else None,
            "operator": props.get("Operator") or props.get("Owner"),
            "country": "NZL",
            "status": (props.get("Status") or "active").lower().split(" - ")[0].strip(),
            "awarded_date": _ms_to_date(props.get("Granted")),
            "expires_date": _ms_to_date(props.get("Expiry")),
            "portal_url": "https://www.nzpam.govt.nz/maps-geoscience/online-permit-register/",
            "attributes": {k: v for k, v in props.items()},
            "geom": geom,
        })

    if not rows:
        log.warning("nzpam-offshore: no features returned")
        await _log_sync_skipped("nzpam", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "nzpam")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    log.info("nzpam-offshore: %d new / %d total", inserted, total)
    await _log_sync("nzpam", inserted, len(rows))
    return inserted


# ── Phase 5: ANP (Brazil) ────────────────────────────────────────────────────

async def sync_anp_brazil() -> int:
    """Fetch Brazilian offshore oil/gas data from ANP open data (two layers).

    Layer 7 (BLOCOS_EXPLORATORIOS_SIRGASPolygon): exploration blocks.
      Fields: COD_BLOCO (code), NOM_BLOCO (name), NOM_BACIA (basin),
              OPERADOR_C (operator), COD_FASE_C (E/P/D phase).
    Layer 6 (CAMPOS_PRODUCAO_SIRGASPolygon): production fields.
      Fields: COD_CAMPO, NOM_CAMPO (name), OPERADOR_C, ETAPA (stage), MED_LAMINA (depth_m).
    Both filtered to AMBIENTE='M' (maritime/offshore). Layer-6 source_ids are prefixed
    'prod_' to avoid collision with layer-7 numeric IDs.
    """
    ANP_BASE = (
        "https://services2.arcgis.com/Az8bZXFPk4TfCJlZ/arcgis/rest/services/"
        "Mapa_OeG_WFL1/FeatureServer"
    )
    rows: list[dict] = []
    _layers_total = 0
    _layers_failed = 0
    _last_exc_name = ""

    # Layer 7 — exploration blocks
    _layers_total += 1
    try:
        features_l7 = await fetch_arcgis_features_url(
            f"{ANP_BASE}/7/query", out_fields="*", extra_params={"where": "AMBIENTE='M'"}
        )
    except Exception as exc:
        log.warning("anp-brazil: layer 7 fetch failed — %s", exc)
        features_l7 = []
        _layers_failed += 1
        _last_exc_name = type(exc).__name__

    for f in features_l7:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        phase = (props.get("COD_FASE_C") or "").upper()
        status = {"E": "exploration", "P": "production", "D": "development"}.get(phase, phase.lower() or "active")
        rows.append({
            "source": "anp",
            "source_id": str(props.get("COD_BLOCO") or props.get("FID") or ""),
            "activity_type": "oil_gas",
            "name": props.get("NOM_BLOCO") or props.get("COD_BLOCO"),
            "operator": props.get("OPERADOR_C"),
            "country": "BRA",
            "status": status,
            "awarded_date": None,
            "expires_date": None,
            "portal_url": "https://www.gov.br/anp/pt-br/assuntos/exploracao-e-producao-de-oleo-e-gas",
            "attributes": {k: v for k, v in props.items()},
            "geom": geom,
        })

    # Layer 6 — production fields
    _layers_total += 1
    try:
        features_l6 = await fetch_arcgis_features_url(
            f"{ANP_BASE}/6/query", out_fields="*", extra_params={"where": "AMBIENTE='M'"}
        )
    except Exception as exc:
        log.warning("anp-brazil: layer 6 fetch failed — %s", exc)
        features_l6 = []
        _layers_failed += 1
        _last_exc_name = type(exc).__name__

    for f in features_l6:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        etapa = (props.get("ETAPA") or "").lower()
        if etapa.startswith("produ"):
            status = "production"
        elif "devolu" in etapa or "devol" in etapa:
            status = "relinquishing"
        else:
            status = "production"
        rows.append({
            "source": "anp",
            "source_id": f"prod_{props.get('FID') or props.get('COD_CAMPO') or ''}",
            "activity_type": "oil_gas",
            "name": props.get("NOM_CAMPO") or str(props.get("COD_CAMPO") or ""),
            "operator": props.get("OPERADOR_C"),
            "country": "BRA",
            "status": status,
            "awarded_date": None,
            "expires_date": None,
            "portal_url": "https://www.gov.br/anp/pt-br/assuntos/exploracao-e-producao-de-oleo-e-gas",
            "attributes": {k: v for k, v in props.items()},
            "geom": geom,
        })

    if not rows:
        log.warning("anp-brazil: no features returned from either layer")
        if _layers_total and _layers_failed == _layers_total:
            await _log_sync_skipped("anp", f"fetch failed: every layer failed ({_last_exc_name})")
        else:
            await _log_sync_skipped("anp", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "anp")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("anp", inserted, len(rows))
    log.info("anp-brazil: %d new / %d total", inserted, len(rows))
    return inserted


# ── Phase 5b: Sodir (Norway) ─────────────────────────────────────────────────

async def sync_sodir_petroleum() -> int:
    """Fetch Norwegian Continental Shelf production licences from Sodir (formerly NPD).

    Source: factmaps.sodir.no DataService FeatureServer layer 3000 (licence).
    Multiple rows per licence (one per company interest) — deduplicated to one
    geometry per prlNpdidLicence, using the first encountered row for operator.
    Fields: prlName (licence number e.g. '001'), cmpLongName (company), prlStatus,
            prlActive ('Y'/'N'), prlDateGranted, prlDateValidTo, prlFactPageUrl.
    """
    SODIR_URL = (
        "https://factmaps.sodir.no/api/rest/services/DataService/Data/"
        "FeatureServer/3000/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(
            SODIR_URL, out_fields="*", extra_params={"where": "prlActive='Y'"}
        )
    except Exception as exc:
        log.warning("sodir-petroleum: fetch failed — %s", exc)
        await _log_sync_skipped("sodir", f"fetch failed: {type(exc).__name__}")
        return 0

    seen_ids: set[str] = set()
    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        licence_id = str(props.get("prlNpdidLicence") or "")
        if licence_id in seen_ids:
            continue
        seen_ids.add(licence_id)
        granted_ms = props.get("prlDateGranted")
        expires_ms = props.get("prlDateValidTo")
        rows.append({
            "source": "sodir",
            "source_id": licence_id,
            "activity_type": "oil_gas",
            "name": props.get("prlName"),
            "operator": props.get("cmpLongName"),
            "country": "NOR",
            "status": (props.get("prlStatus") or "ACTIVE").lower(),
            "awarded_date": datetime.fromtimestamp(granted_ms / 1000) if granted_ms else None,
            "expires_date": datetime.fromtimestamp(expires_ms / 1000) if expires_ms else None,
            "portal_url": props.get("prlFactPageUrl") or "https://factpages.sodir.no/",
            "attributes": {k: v for k, v in props.items()},
            "geom": geom,
        })

    if not rows:
        log.warning("sodir-petroleum: no features returned")
        await _log_sync_skipped("sodir", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "sodir")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("sodir", inserted, len(rows))
    log.info("sodir-petroleum: %d new / %d total", inserted, total)
    return inserted


# ── Phase 5c: NSTA (UK) ──────────────────────────────────────────────────────

async def sync_nsta_petroleum() -> int:
    """Fetch UK offshore petroleum licences from NSTA (North Sea Transition Authority).

    Source: NSTA_GIS ArcGIS FeatureServer — 'UKCS offshore petroleum licences WGS84'.
    One polygon per licence (aggregated from constituent blocks by NSTA).
    Fields: LICNO (number), LICREF (reference e.g. 'P250'), LICTYPE, LICSTATUS
            ('Extant'/'Surrendered'/'Expired'), SUBOPORG (operator), LICORGGRP,
            LICSTARTDT, LICENDDT, AGREED_KM2.
    """
    NSTA_URL = (
        "https://services-eu1.arcgis.com/OZMfUznmLTnWccBc/arcgis/rest/services/"
        "UKCS offshore petroleum licences WGS84/FeatureServer/0/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(
            NSTA_URL, out_fields="*", extra_params={"where": "LOCATION='OFFSHORE'"}
        )
    except Exception as exc:
        log.warning("nsta-petroleum: fetch failed — %s", exc)
        await _log_sync_skipped("nsta", f"fetch failed: {type(exc).__name__}")
        return 0

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        start_ms = props.get("LICSTARTDT")
        end_ms = props.get("LICENDDT")
        # LICSTATUS: 'Extant' → active, else lower()
        raw_status = (props.get("LICSTATUS") or "").lower()
        status = "active" if raw_status == "extant" else (raw_status or "unknown")
        # Operator: SUBOPORG contains company name + company number in parens — strip number
        raw_op = props.get("SUBOPORG") or props.get("LICORGGRP") or ""
        import re as _re
        operator = _re.sub(r"\s*\([^)]+\)\s*", " ", raw_op).strip() or None
        rows.append({
            "source": "nsta",
            "source_id": str(props.get("DATAPID") or props.get("LICNO") or ""),
            "activity_type": "oil_gas",
            "name": props.get("LICREF"),
            "operator": operator,
            "country": "GBR",
            "status": status,
            "awarded_date": datetime.fromtimestamp(start_ms / 1000) if start_ms else None,
            "expires_date": datetime.fromtimestamp(end_ms / 1000) if end_ms else None,
            "portal_url": "https://www.nstauthority.co.uk/data-centre/nsta-open-data/",
            "attributes": {k: v for k, v in props.items()},
            "geom": geom,
        })

    if not rows:
        log.warning("nsta-petroleum: no features returned")
        await _log_sync_skipped("nsta", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "nsta")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("nsta", inserted, len(rows))
    log.info("nsta-petroleum: %d new / %d total", inserted, total)
    return inserted


# ── Phase 5d: CNH Mexico ─────────────────────────────────────────────────────
# SSL verification is disabled for exactly ONE host: agsserver.sigsa.info (the
# Mexican CNH/PEMEX ArcGIS server behind sync_cnh_mexico()), documented since
# this function was introduced as serving an expired/self-signed certificate —
# a real and common failure mode for Mexican government GIS servers. Checked
# 2026-09-06: no network egress from this sandbox to re-run the TLS handshake,
# so this is a scoping fix, not a re-verification of the underlying claim.
# `_NO_SSL_ALLOWED_HOSTS` hard-scopes the exception to that one host so a future
# caller can't silently reuse this helper (and its disabled verification) for
# an arbitrary URL.
_NO_SSL_ALLOWED_HOSTS = {"agsserver.sigsa.info"}


async def fetch_arcgis_no_ssl(url: str, out_fields: str = "*", extra_params: dict | None = None) -> list[dict]:
    """Like fetch_arcgis_features_url but skips SSL verification.
    Restricted to _NO_SSL_ALLOWED_HOSTS (agsserver.sigsa.info — expired/self-signed
    certificate). Raises ValueError for any other host rather than silently
    disabling TLS verification for it.
    """
    host = urlparse(url).hostname or ""
    if host not in _NO_SSL_ALLOWED_HOSTS:
        raise ValueError(
            f"fetch_arcgis_no_ssl: refusing to skip TLS verification for unexpected host {host!r} "
            f"(allowed: {sorted(_NO_SSL_ALLOWED_HOSTS)})"
        )
    all_features: list[dict] = []
    offset = 0
    async with httpx.AsyncClient(timeout=60, verify=False) as client:
        while True:
            params = {
                "where": "1=1",
                "outFields": out_fields,
                "f": "geojson",
                "resultRecordCount": 1000,
                "resultOffset": offset,
                **(extra_params or {}),
            }
            r = await _get_with_retry(client, url, params=params, label="arcgis page")
            features = r.json().get("features", [])
            all_features.extend(features)
            if len(features) < 1000:
                break
            offset += 1000
    return all_features


async def sync_cnh_mexico() -> int:
    """Fetch Mexican offshore hydrocarbon assignments from CNH/PEMEX via SIGSA ArcGIS.

    Source: agsserver.sigsa.info/arcgis/rest/services/hiac/Infraestructura/MapServer
    Uses PEMEX Asignaciones layer (layer 4) filtered to ENTIDAD='Marino' (offshore).
    SSL verification disabled — server has an expired certificate (common on Mexican gov GIS).
    Operator is always PEMEX (all features are PEMEX government assignments).
    Fields: ASIGNACION (full name), Id (assignment ID), TIPO (type),
            REGION (Aguas someras/Aguas profundas), Fe_otor (award date as string).
    """
    CNH_URL = (
        "https://agsserver.sigsa.info/arcgis/rest/services/"
        "hiac/Infraestructura/MapServer/4/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_no_ssl(
            CNH_URL, out_fields="*", extra_params={"where": "ENTIDAD='Marino'"}
        )
    except Exception as exc:
        log.warning("cnh-mexico: fetch failed — %s", exc)
        await _log_sync_skipped("cnh", f"fetch failed: {type(exc).__name__}")
        return 0

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        rows.append({
            "source": "cnh",
            "source_id": str(props.get("ID_ASIGNACION") or props.get("OBJECTID") or ""),
            "activity_type": "oil_gas",
            "name": props.get("ASIGNACION") or props.get("Id"),
            "operator": "PEMEX",
            "country": "MEX",
            "status": "active",
            "awarded_date": None,
            "expires_date": None,
            "portal_url": "https://www.gob.mx/cnh",
            "attributes": {k: v for k, v in props.items()},
            "geom": geom,
        })

    if not rows:
        log.warning("cnh-mexico: no features returned")
        await _log_sync_skipped("cnh", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "cnh")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("cnh", inserted, len(rows))
    log.info("cnh-mexico: %d new / %d total", inserted, total)
    return inserted


# ── Phase 5e: Crown Estate Scotland ──────────────────────────────────────────

async def sync_crown_estate_scotland() -> int:
    """Fetch Scottish offshore wind lease areas from Crown Estate Scotland (CES).

    Two datasets combined under source='crown_estate_scotland':
    1. Offshore Wind (58 sites): operational and in-development leases.
       name=Property_Description, operator=Tenant_Name, status=Project_Phase.
    2. ScotWind Offers (20 sites): new-round option agreements not yet in dataset 1.
       name=Lead applicant name, operator=Lead_App, status='option_agreement'.
    Source_ids are prefixed to avoid collision between datasets.
    """
    CES_BASE = "https://services3.arcgis.com/nGV4jiurzcahJ9LV/arcgis/rest/services"
    rows: list[dict] = []
    _layers_total = 0
    _layers_failed = 0
    _last_exc_name = ""

    # Dataset 1: existing offshore wind leases
    _layers_total += 1
    try:
        features_ow = await fetch_arcgis_features_url(
            f"{CES_BASE}/Offshore_Wind_Crown_Estate_Scotland/FeatureServer/0/query",
            out_fields="*",
        )
    except Exception as exc:
        log.warning("crown-estate-scotland: Offshore Wind fetch failed — %s", exc)
        features_ow = []
        _layers_failed += 1
        _last_exc_name = type(exc).__name__

    for f in features_ow:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        rows.append({
            "source": "crown_estate_scotland",
            "source_id": f"ow_{props.get('OBJECTID_1') or props.get('OBJECTID') or ''}",
            "activity_type": "offshore_wind",
            "name": props.get("Property_Description"),
            "operator": props.get("Tenant_Name"),
            "country": "GBR",
            "status": (props.get("Project_Phase") or "").lower().replace(" ", "_") or "active",
            "awarded_date": None,
            "expires_date": None,
            "portal_url": "https://www.crownestatescotland.com/our-portfolio/offshore-wind-and-marine",
            "attributes": {k: v for k, v in props.items()},
            "geom": geom,
        })

    # Dataset 2: ScotWind option agreements
    _layers_total += 1
    try:
        features_sw = await fetch_arcgis_features_url(
            f"{CES_BASE}/ScotWind_Offers_Crown_Estate_Scotland/FeatureServer/0/query",
            out_fields="*",
        )
    except Exception as exc:
        log.warning("crown-estate-scotland: ScotWind Offers fetch failed — %s", exc)
        features_sw = []
        _layers_failed += 1
        _last_exc_name = type(exc).__name__

    for f in features_sw:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        rows.append({
            "source": "crown_estate_scotland",
            "source_id": f"sw_{props.get('Id') or props.get('OBJECTID') or ''}",
            "activity_type": "offshore_wind",
            "name": props.get("Lead_App"),
            "operator": props.get("Lead_App"),
            "country": "GBR",
            "status": "option_agreement",
            "awarded_date": None,
            "expires_date": None,
            "portal_url": "https://www.crownestatescotland.com/our-portfolio/offshore-wind-and-marine/scotwind",
            "attributes": {k: v for k, v in props.items()},
            "geom": geom,
        })

    if not rows:
        log.warning("crown-estate-scotland: no features returned from either dataset")
        if _layers_total and _layers_failed == _layers_total:
            await _log_sync_skipped("crown_estate_scotland", f"fetch failed: every layer failed ({_last_exc_name})")
        else:
            await _log_sync_skipped("crown_estate_scotland", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "crown_estate_scotland")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("crown_estate_scotland", inserted, len(rows))
    log.info("crown-estate-scotland: %d new / %d total (ow=%d sw=%d)", inserted, total, len(features_ow), len(features_sw))
    return inserted


# ── Phase 5f: ESDM Indonesia ─────────────────────────────────────────────────

async def sync_esdm_indonesia() -> int:
    """Fetch Indonesian conventional oil/gas working areas from ESDM One Map.

    Source: geoportal.esdm.go.id MapServer DMEW/Wilayah_Kerja_Migas_Konvensional/0.
    Owner: Direktorat Pembinaan Usaha Hulu Minyak Dan Gas Bumi (upstream directorate).
    Mix of onshore + offshore PSC blocks — same posture as Sodir/NSTA.
    Fields: namobj (name), oprblk (operator), effdat/expdat (epoch ms),
            status (EXPLORATION / PRODUCTION / PENGEMBANGAN=development).
    """
    ESDM_URL = (
        "https://geoportal.esdm.go.id/gis3/rest/services/DMEW/"
        "Wilayah_Kerja_Migas_Konvensional/MapServer/0/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(ESDM_URL, out_fields="*")
    except Exception as exc:
        log.warning("esdm-indonesia: fetch failed — %s", exc)
        await _log_sync_skipped("esdm", f"fetch failed: {type(exc).__name__}")
        return 0

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        eff_ms = props.get("effdat")
        exp_ms = props.get("expdat")
        raw_status = (props.get("status") or "").lower()
        if raw_status == "exploration":
            status = "exploration"
        elif raw_status == "production":
            status = "production"
        elif raw_status == "pengembangan":
            status = "development"
        else:
            status = raw_status or "active"
        rows.append({
            "source": "esdm",
            "source_id": str(props.get("objectid") or ""),
            "activity_type": "oil_gas",
            "name": props.get("namobj"),
            "operator": props.get("oprblk"),
            "country": "IDN",
            "status": status,
            "awarded_date": datetime.fromtimestamp(eff_ms / 1000) if eff_ms else None,
            "expires_date": datetime.fromtimestamp(exp_ms / 1000) if exp_ms else None,
            "portal_url": "https://geoportal.esdm.go.id/migas/",
            "attributes": {k: v for k, v in props.items()},
            "geom": geom,
        })

    if not rows:
        log.warning("esdm-indonesia: no features returned")
        await _log_sync_skipped("esdm", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "esdm")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("esdm", inserted, len(rows))
    log.info("esdm-indonesia: %d new / %d total", inserted, total)
    return inserted


# ── Phase 5g: PASA South Africa ──────────────────────────────────────────────

async def sync_pasa_sa() -> int:
    """Fetch South African offshore petroleum blocks and rights from PASA.

    Source: geoportal.petroleumagencysa.com Storefront/Exploration_and_Production.
    Four layers ingested under source='pasa' with prefixed source_ids to avoid
    OBJECTID collisions across layers.
    L13 (108): Shallow water Blocks — name = LABEL block code
    L14 (101): Deep water Blocks    — name = LABEL block code
    L15 (152): Petroleum ExplorationRight — operator anonymised by PASA
    L16  (15): Petroleum TCP (Technical Cooperation Permit) — operator anonymised
    """
    BASE = (
        "https://geoportal.petroleumagencysa.com/arcgis/rest/services/"
        "Storefront/Exploration_and_Production/MapServer"
    )
    layer_specs = [
        (13, "shallow_", "oil_gas", "available_block",        "Shallow Block {label}"),
        (14, "deep_",    "oil_gas", "available_block",        "Deep Block {label}"),
        (15, "expr_",    "oil_gas", "exploration",            "Exploration Right #{oid}"),
        (16, "tcp_",     "oil_gas", "technical_cooperation",  "TCP #{oid}"),
    ]
    rows: list[dict] = []
    _layers_total = 0
    _layers_failed = 0
    _last_exc_name = ""
    for lid, prefix, act_type, status, tmpl in layer_specs:
        _layers_total += 1
        try:
            features = await fetch_arcgis_features_url(f"{BASE}/{lid}/query", out_fields="*")
        except Exception as exc:
            log.warning("pasa-sa: layer %d fetch failed — %s", lid, exc)
            _layers_failed += 1
            _last_exc_name = type(exc).__name__
            continue
        for f in features:
            props = f.get("properties") or {}
            geom = f.get("geometry")
            if not geom:
                continue
            oid = props.get("OBJECTID") or props.get("OBJECTID_1")
            label = props.get("LABEL")
            rows.append({
                "source": "pasa",
                "source_id": f"{prefix}{oid}",
                "activity_type": act_type,
                "name": tmpl.format(label=label or oid, oid=oid),
                "operator": None,
                "country": "ZAF",
                "status": status,
                "awarded_date": None,
                "expires_date": None,
                "portal_url": "https://www.petroleumagencysa.com/",
                "attributes": {k: v for k, v in props.items()},
                "geom": geom,
            })

    if not rows:
        log.warning("pasa-sa: no features returned from any layer")
        if _layers_total and _layers_failed == _layers_total:
            await _log_sync_skipped("pasa", f"fetch failed: every layer failed ({_last_exc_name})")
        else:
            await _log_sync_skipped("pasa", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "pasa")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("pasa", inserted, len(rows))
    log.info("pasa-sa: %d new / %d total", inserted, total)
    return inserted


# ── Phase 5: MRA Papua New Guinea ────────────────────────────────────────────

async def sync_mra_png_dsm() -> int:
    """Fetch PNG seabed-mining licence areas from MRA Landfolio portal."""
    MRA_URL = (
        "https://portal.mra.gov.pg/server/rest/services/Public/Mining_Tenements/MapServer/0/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(MRA_URL, out_fields="*")
    except Exception as exc:
        log.warning("mra-png-dsm: fetch failed — %s", exc)
        await _log_sync_skipped("mra_png", f"fetch failed: {type(exc).__name__}")
        return 0

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        name_val = props.get("TENEMENT_NO") or props.get("NAME") or props.get("OBJECTID")
        rows.append({
            "source": "mra_png",
            "source_id": str(props.get("TENEMENT_NO") or props.get("OBJECTID") or ""),
            "activity_type": "seabed_mining",
            "name": str(name_val) if name_val else None,
            "operator": props.get("HOLDER") or props.get("COMPANY"),
            "country": "PNG",
            "status": (props.get("STATUS") or "active").lower(),
            "awarded_date": None,
            "expires_date": None,
            "portal_url": "https://portal.mra.gov.pg",
            "attributes": {k: v for k, v in props.items()},
            "geom": geom,
        })

    if not rows:
        log.warning("mra-png-dsm: no features returned")
        await _log_sync_skipped("mra_png", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "mra_png")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    log.info("mra-png-dsm: %d new / %d total", inserted, total)
    await _log_sync("mra_png", inserted, len(rows))
    return inserted


# ── Phase 5: MME Namibia ─────────────────────────────────────────────────────

async def sync_mme_nam_dsm() -> int:
    """Fetch Namibia seabed-mining licences from MME Landfolio portal."""
    MME_URL = (
        "https://portals.landfolio.com/namibia/Server/rest/services/Public/"
        "Mining_Tenements/MapServer/0/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(MME_URL, out_fields="*")
    except Exception as exc:
        log.warning("mme-namibia-dsm: fetch failed — %s", exc)
        await _log_sync_skipped("mme_nam", f"fetch failed: {type(exc).__name__}")
        return 0

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        rows.append({
            "source": "mme_nam",
            "source_id": str(props.get("TENEMENT_NO") or props.get("OBJECTID") or ""),
            "activity_type": "seabed_mining",
            "name": props.get("TENEMENT_NO") or props.get("NAME"),
            "operator": props.get("HOLDER") or props.get("COMPANY"),
            "country": "NAM",
            "status": (props.get("STATUS") or "active").lower(),
            "awarded_date": None,
            "expires_date": None,
            "portal_url": "https://portals.landfolio.com/namibia",
            "attributes": {k: v for k, v in props.items()},
            "geom": geom,
        })

    if not rows:
        log.warning("mme-namibia-dsm: no features returned")
        await _log_sync_skipped("mme_nam", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "mme_nam")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    log.info("mme-namibia-dsm: %d new / %d total", inserted, total)
    await _log_sync("mme_nam", inserted, len(rows))
    return inserted


# ── Phase 5: SBMA Cook Islands ───────────────────────────────────────────────

async def sync_sbma_ck() -> int:
    """Fetch Cook Islands seabed-mining tenements from SBMA Landfolio cadastre.

    SBMA uses Trimble Landfolio. The service URL is tried at runtime so a domain
    migration doesn't break the sync — we probe several known candidate bases and
    resolve the tenement layer by name rather than by hardcoded layer ID.

    If the service is unreachable the function logs a warning and exits cleanly;
    any data already in the DB persists until the next successful run.
    """
    async with db.pool.acquire() as conn:
        last = await conn.fetchval(
            "SELECT last_synced_at FROM sync_log WHERE source = 'sbma-cook-islands'"
        )
    if last and (datetime.now(tz=timezone.utc) - last).days < 7:
        log.info("sbma-cook-islands: skipping — synced %s", last.date())
        return 0

    # Known Landfolio bases to try in order; SBMA may migrate subdomains.
    CANDIDATE_BASES = [
        "https://cooks.landfolio.com/server/rest/services/Public/Mining_Tenements/MapServer",
        "https://cookislands.landfolio.com/server/rest/services/Public/Mining_Tenements/MapServer",
        "https://sbma.landfolio.com/server/rest/services/Public/Mining_Tenements/MapServer",
    ]
    # Layer names used across Landfolio deployments (first match wins).
    LAYER_NAMES = {"Tenements", "Mining Tenements", "Applications", "Licences", "Exploration"}
    # Status codes that mean the tenement is no longer active.
    INACTIVE = {"SURRENDERED", "EXPIRED", "REFUSED", "WITHDRAWN", "REVOKED", "TERMINATED"}

    async def _resolve_tenement_url() -> str | None:
        async with httpx.AsyncClient(timeout=30) as client:
            for base in CANDIDATE_BASES:
                try:
                    try:
                        r = await _get_with_retry(
                            client, f"{base}?f=json", label="arcgis probe")
                    except Exception:
                        continue   # this candidate base is not the one; try the next

                    data = r.json()
                    layers = data.get("layers", [])
                    for L in layers:
                        if (L.get("name") or "").strip() in LAYER_NAMES:
                            return f"{base}/{L['id']}/query"
                    # Last-ditch: first polygon layer in the service
                    for L in layers:
                        if "poly" in (L.get("geometryType") or "").lower():
                            log.info("sbma-cook-islands: falling back to layer '%s' at %s",
                                     L.get("name"), base)
                            return f"{base}/{L['id']}/query"
                except Exception as exc:
                    log.debug("sbma-cook-islands: candidate %s failed — %s", base, exc)
        return None

    def _first(props: dict, *keys: str):
        for k in keys:
            v = props.get(k)
            if v not in (None, ""):
                return v
        return None

    url = await _resolve_tenement_url()
    if not url:
        log.warning("sbma-cook-islands: no live Landfolio service found at any candidate URL")
        await _log_sync_skipped(
            "sbma-cook-islands", "no Landfolio candidate base resolved")
        return 0

    try:
        features = await fetch_arcgis_features_url(url)
    except Exception as exc:
        log.warning("sbma-cook-islands: fetch failed — %s", exc)
        await _log_sync_skipped(
            "sbma-cook-islands", f"fetch failed: {type(exc).__name__}")
        return 0

    rows: list[dict] = []
    for f in features:
        props = f.get("properties") or {}
        geom  = f.get("geometry")
        if not geom:
            continue

        tid    = _first(props, "TENEMENT_NUMBER", "TENEMENT_NO", "LICENCE_NO",
                               "APPLICATION_ID", "TITLE_NUMBER", "OBJECTID")
        status = (_first(props, "STATUS", "TENEMENT_STATUS", "STATUS_DESC") or "").strip().upper()
        if not tid or status in INACTIVE:
            continue

        rows.append({
            "source":        "sbma_ck",
            "source_id":     str(tid),
            "activity_type": "seabed_mining",
            "name":          _first(props, "TENEMENT_NUMBER", "TENEMENT_NO", "TITLE_NAME") or str(tid),
            "operator":      _first(props, "HOLDER_NAME", "HOLDER", "APPLICANT", "COMPANY"),
            "country":       "Cook Islands",
            "status":        status.lower() or "active",
            "awarded_date":  _coerce_date(_first(props, "GRANT_DATE", "ISSUE_DATE",
                                                         "EFFECTIVE_DATE", "START_DATE")),
            "expires_date":  _coerce_date(_first(props, "EXPIRY_DATE", "EXPIRATION_DATE",
                                                         "END_DATE")),
            "portal_url":    "https://sbma.gov.ck/map-of-applications",
            "attributes":    props,
            "geom":          geom,
        })

    if not rows:
        log.warning("sbma-cook-islands: no active tenements after status filter")
        await _log_sync_skipped("sbma-cook-islands", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "sbma_ck")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("sbma-cook-islands", inserted, total)
    log.info("sbma-cook-islands: %d new / %d total", inserted, total)
    return inserted


# ── CNSOPB (Canada — Nova Scotia) ────────────────────────────────────────────

async def sync_cnsopb_petroleum() -> int:
    """Fetch Nova Scotia offshore petroleum licences from NRCan/CNSOPB ArcGIS server.

    Three layers from the Nova_Scotia_Offshore_Petroleum MapServer:
      Layer 4 — Georges Bank Permits  (fields: LIC_ID, LIC_TYPE, LIC_REPRES, EFF_DATE, AREA_HA_LU)
      Layer 5 — Production Licences   (fields: LICENSE_NO, P_TYPE, KEYWORD, START_DATE, End_Date, AREA_HA_LU)
      Layer 6 — Significant Discovery Licences (fields: LICENSE_NO, P_TYPE, KEYWORD, START_DATE, AREA_HA_LU)
    Dates are YYYYMMDD integers. source_ids are prefixed L4_/L5_/L6_ to avoid collision across layers.
    """
    BASE = (
        "https://maps-cartes.services.geo.ca/server_serveur/rest/services/NRCan/"
        "Nova_Scotia_Offshore_Petroleum_en/MapServer"
    )
    LAYERS = [
        (4, "LIC_ID",    "LIC_TYPE",  "LIC_REPRES", "EFF_DATE",   None,        "L4_"),
        (5, "LICENSE_NO", "P_TYPE",   "KEYWORD",    "START_DATE", "End_Date",  "L5_"),
        (6, "LICENSE_NO", "P_TYPE",   "KEYWORD",    "START_DATE", None,        "L6_"),
    ]

    def _yyyymmdd(v):
        if v is None:
            return None
        try:
            return datetime.strptime(str(int(v)), "%Y%m%d").date().isoformat()
        except Exception:
            return None

    rows: list[dict] = []
    _layers_total = 0
    _layers_failed = 0
    _last_exc_name = ""
    for layer_id, id_field, type_field, op_field, awarded_field, expires_field, prefix in LAYERS:
        url = f"{BASE}/{layer_id}/query"
        _layers_total += 1
        try:
            features = await fetch_arcgis_features_url(url, out_fields="*")
        except Exception as exc:
            log.warning("cnsopb: layer %d fetch failed — %s", layer_id, exc)
            _layers_failed += 1
            _last_exc_name = type(exc).__name__
            continue
        for f in features:
            props = f.get("properties") or {}
            geom = f.get("geometry")
            if not geom:
                continue
            rows.append({
                "source":        "cnsopb",
                "source_id":     prefix + str(props.get(id_field) or props.get("OBJECTID") or ""),
                "activity_type": "oil_gas",
                "name":          str(props.get(id_field)) if props.get(id_field) else None,
                "operator":      props.get(op_field),
                "country":       "CAN",
                "status":        "active",
                "awarded_date":  _yyyymmdd(props.get(awarded_field)) if awarded_field else None,
                "expires_date":  _yyyymmdd(props.get(expires_field)) if expires_field else None,
                "portal_url":    "https://www.cnsopb.ns.ca/",
                "attributes":    {k: v for k, v in props.items()},
                "geom":          geom,
            })

    if not rows:
        log.warning("cnsopb: no features returned")
        if _layers_total and _layers_failed == _layers_total:
            await _log_sync_skipped("cnsopb", f"fetch failed: every layer failed ({_last_exc_name})")
        else:
            await _log_sync_skipped("cnsopb", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "cnsopb")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("cnsopb", inserted, total)
    log.info("cnsopb: %d new / %d total", inserted, total)
    return inserted


# ── C-NLOPB (Canada — Newfoundland & Labrador) ───────────────────────────────

async def sync_cnlopb_petroleum() -> int:
    """Fetch NL offshore petroleum licences from C-NLOPB ArcGIS Online (energygisnl).

    Three separate FeatureServer layers, all on services8.arcgis.com:
      EL_  — Active Exploration Licences (COMPANYANALYSIS_gdb layer 13, ~30 features)
      SDL_ — Significant Discovery Licences (Significant_Discovery_Licence layer 0, ~67 features)
      PL_  — Production Licences (Prod_Licence layer 105, ~14 features)
    All dates are Unix millisecond epoch. source_ids are prefixed to prevent collision.
    """
    LAYERS = [
        # (url, name_field, op_field, op_fallback, awarded_field, expires_field, status_const, prefix)
        (
            "https://services8.arcgis.com/jSziFsB3BeiveI9A/arcgis/rest/services/COMPANYANALYSIS_gdb/FeatureServer/13/query",
            "PARCEL_NO", "REP",       "A_IH1",    "DATEEFFECT", "EXPIRY2",   None,          "EL_",
        ),
        (
            "https://services8.arcgis.com/jSziFsB3BeiveI9A/arcgis/rest/services/Significant_Discovery_Licence/FeatureServer/0/query",
            "WELL",      "IH1_Rep",   "Operator", "DATEEFFECT", None,        None,           "SDL_",
        ),
        (
            "https://services8.arcgis.com/jSziFsB3BeiveI9A/arcgis/rest/services/Prod_Licence/FeatureServer/105/query",
            "PLATFORMS", "Operators", "IH1_Rep",  "DATEEFFECT", None,        "production",  "PL_",
        ),
    ]

    def _ms_to_date(ms):
        if ms is None:
            return None
        try:
            return datetime.utcfromtimestamp(int(ms) / 1000).date().isoformat()
        except Exception:
            return None

    rows: list[dict] = []
    _layers_total = 0
    _layers_failed = 0
    _last_exc_name = ""
    for url, name_f, op_f, op_fb, awarded_f, expires_f, status_const, prefix in LAYERS:
        _layers_total += 1
        try:
            features = await fetch_arcgis_features_url(url, out_fields="*")
        except Exception as exc:
            log.warning("cnlopb: %s fetch failed — %s", prefix, exc)
            _layers_failed += 1
            _last_exc_name = type(exc).__name__
            continue
        for f in features:
            props = f.get("properties") or {}
            geom = f.get("geometry")
            if not geom:
                continue
            name_val = props.get(name_f)
            # Production names: strip whitespace-only strings
            if isinstance(name_val, str):
                name_val = name_val.strip() or None
            expires = None
            if expires_f:
                expires = _ms_to_date(props.get(expires_f))
                if expires is None and expires_f == "EXPIRY2":
                    expires = _ms_to_date(props.get("EXPIRY1"))
            status = status_const or (props.get("Status") or props.get("Activity") or "active").lower()
            rows.append({
                "source":        "cnlopb",
                "source_id":     prefix + str(props.get("PARCEL_NO") or props.get("parcel") or props.get("TYPENUM") or props.get("OBJECTID") or ""),
                "activity_type": "oil_gas",
                "name":          str(name_val) if name_val else None,
                "operator":      props.get(op_f) or props.get(op_fb),
                "country":       "CAN",
                "status":        status,
                "awarded_date":  _ms_to_date(props.get(awarded_f)),
                "expires_date":  expires,
                "portal_url":    "https://www.cnlopb.ca/",
                "attributes":    {k: v for k, v in props.items()},
                "geom":          geom,
            })

    if not rows:
        log.warning("cnlopb: no features returned")
        if _layers_total and _layers_failed == _layers_total:
            await _log_sync_skipped("cnlopb", f"fetch failed: every layer failed ({_last_exc_name})")
        else:
            await _log_sync_skipped("cnlopb", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "cnlopb")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("cnlopb", inserted, total)
    log.info("cnlopb: %d new / %d total", inserted, total)
    return inserted


# ── GEUS / DEA (Denmark North Sea) ───────────────────────────────────────────

async def sync_dea_dk_petroleum() -> int:
    """Fetch Danish North Sea petroleum licences from GEUS SAMBA database via WFS.

    Source: data.geus.dk/geusmap WFS 2.0.0, typeName=samba_licences, outputFormat=GEOJSON.
    31 features total — no pagination needed. Dates are ISO strings (YYYY-MM-DD).
    Fields: licence_id, licence_name, polygon_name, start_date, end_date,
            licence_type, licensee_name.
    """
    # The path component is the SRS code — `4326.jsp` returns CRS84 (lon/lat
    # WGS84) so geometries can go straight into PostGIS without reprojection.
    # `25832.jsp` returns the same data in UTM zone 32N meters and was used
    # earlier — replaced after every Danish licence ended up at lat ≈ 6e6.
    WFS_URL = (
        "https://data.geus.dk/geusmap/ows/4326.jsp"
        "?service=WFS&request=GetFeature&version=2.0.0"
        "&typeName=samba_licences&outputFormat=GEOJSON"
    )
    rows: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await _get_with_retry(client, WFS_URL, label="dea-dk wfs")
            data = r.json()
    except Exception as exc:
        log.warning("dea-dk: fetch failed — %s", exc)
        await _log_sync_skipped("dea-dk", f"fetch failed: {type(exc).__name__}")
        return 0

    features = data.get("features") or []
    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        name = props.get("licence_name") or props.get("polygon_name")
        rows.append({
            "source":        "dea_dk",
            "source_id":     str(props.get("licence_id") or ""),
            "activity_type": "oil_gas",
            "name":          name,
            "operator":      props.get("licensee_name"),
            "country":       "DNK",
            "status":        (props.get("licence_type") or "active").lower(),
            "awarded_date":  (props.get("start_date") or "")[:10] or None,
            "expires_date":  (props.get("end_date") or "")[:10] or None,
            "portal_url":    "https://data.geus.dk/geusmap/",
            "attributes":    {k: v for k, v in props.items()},
            "geom":          geom,
        })

    if not rows:
        log.warning("dea-dk: no features returned")
        await _log_sync_skipped("dea-dk", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "dea_dk")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("dea-dk", inserted, total)
    log.info("dea-dk: %d new / %d total", inserted, total)
    return inserted


# ── CCS Phase A: Sodir CO₂ storage licences (Norway) ─────────────────────────

async def sync_sodir_co2() -> int:
    """Fetch Norwegian CO₂ storage licences from Sodir FactMaps (Layer 626).

    Source: factmaps.sodir.no/api/rest/services/Factmaps/FactMapsWGS84/FeatureServer/626
    'CO2 licence - current with geometry' — 13 active licences (Apr 2026).
    Fields: baaNpdidBsnsArrArea (id), baaName (licence number e.g. EL001),
            cmpLongName (operator), baaDateApproved, baaDateValidTo, baaActive,
            baaFactPageUrl.
    """
    SODIR_CO2_URL = (
        "https://factmaps.sodir.no/api/rest/services/Factmaps/FactMapsWGS84/"
        "FeatureServer/626/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(
            SODIR_CO2_URL, out_fields="*", extra_params={"where": "baaActive='Y'"}
        )
    except Exception as exc:
        log.warning("sodir-co2: fetch failed — %s", exc)
        await _log_sync_skipped("sodir_co2", f"fetch failed: {type(exc).__name__}")
        return 0

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        approved_ms = props.get("baaDateApproved")
        expires_ms = props.get("baaDateValidTo")
        rows.append({
            "source":        "sodir_co2",
            "source_id":     str(props.get("baaNpdidBsnsArrArea") or ""),
            "activity_type": "ccs_storage",
            "name":          props.get("baaName"),
            "operator":      props.get("cmpLongName"),
            "country":       "NOR",
            "status":        "active",
            "awarded_date":  datetime.fromtimestamp(approved_ms / 1000) if approved_ms else None,
            "expires_date":  datetime.fromtimestamp(expires_ms / 1000) if expires_ms else None,
            "portal_url":    props.get("baaFactPageUrl") or "https://factpages.sodir.no/",
            "attributes":    {k: v for k, v in props.items()},
            "geom":          geom,
        })

    if not rows:
        log.warning("sodir-co2: no features returned")
        await _log_sync_skipped("sodir_co2", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "sodir_co2")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("sodir_co2", inserted, total)
    log.info("sodir-co2: %d new / %d total", inserted, total)
    return inserted


# ── CCS Phase A: NSTA carbon storage licences (UK) ───────────────────────────

async def sync_nsta_co2() -> int:
    """Fetch UK carbon storage licences from NSTA ArcGIS (UKCS CS licences WGS84).

    Source: services-eu1.arcgis.com/OZMfUznmLTnWccBc — 'UKCS current carbon
    storage licences WGS84' FeatureServer layer 0.
    27 licences total. Fields: LICREF, LICNAME, EXPLO_OPR,
    RNDNO, LICSTATUS, LICSTARTDT, LICDOCURL, PUBREGURL.
    """
    # NSTA republished this layer (Jun 2026): the old space-separated slug is now
    # token-gated (HTTP 499). The public equivalent uses an underscore/parenthesis
    # slug and renamed CS_LICSTAT -> LICSTATUS. Same 27 polygon features.
    NSTA_CO2_URL = (
        "https://services-eu1.arcgis.com/OZMfUznmLTnWccBc/arcgis/rest/services/"
        "UKCS_current_carbon_storage_licences_(WGS84)/FeatureServer/0/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(NSTA_CO2_URL, out_fields="*")
    except Exception as exc:
        log.warning("nsta-co2: fetch failed — %s", exc)
        await _log_sync_skipped("nsta_co2", f"fetch failed: {type(exc).__name__}")
        return 0

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        start_ms = props.get("LICSTARTDT")
        rows.append({
            "source":        "nsta_co2",
            "source_id":     str(props.get("LICREF") or props.get("LICNAME") or ""),
            "activity_type": "ccs_storage",
            "name":          props.get("LICNAME") or props.get("LICREF"),
            "operator":      props.get("EXPLO_OPR"),
            "country":       "GBR",
            "status":        (props.get("LICSTATUS") or props.get("CS_LICSTAT") or "current").lower(),
            "awarded_date":  datetime.fromtimestamp(start_ms / 1000) if start_ms else None,
            "expires_date":  None,
            "portal_url":    props.get("PUBREGURL") or "https://www.nstauthority.co.uk/licensing-consents/carbon-storage/",
            "attributes":    {k: v for k, v in props.items()},
            "geom":          geom,
        })

    if not rows:
        log.warning("nsta-co2: no features returned")
        await _log_sync_skipped("nsta_co2", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "nsta_co2")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("nsta_co2", inserted, total)
    log.info("nsta-co2: %d new / %d total", inserted, total)
    return inserted


# ── Phase B: ANH Colombia offshore blocks ────────────────────────────────────

async def sync_anh_colombia() -> int:
    """Fetch Colombian offshore hydrocarbon blocks from ANH GeoVisor.

    Source: services1.arcgis.com/RtKXiUlG81mjGg9f/arcgis/rest/services/tierras/FeatureServer/0
    Filter: SUPERFICIE='COSTA AFUERA' (offshore only; 15 of 484 total blocks, Apr 2026).
    Fields: CONTRAT_ID (id), CONTRATO_N (block name), AREA_NOMBR (area name),
            OPERADOR, ESTAD_AREA (status), CLASIFICAC, TIPO_CONTR, CUENCA_SED, FECHA_FIRM.
    """
    ANH_URL = (
        "https://services1.arcgis.com/RtKXiUlG81mjGg9f/arcgis/rest/services/"
        "tierras/FeatureServer/0/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(
            ANH_URL, out_fields="*",
            extra_params={"where": "SUPERFICIE='COSTA AFUERA'"}
        )
    except Exception as exc:
        log.warning("anh-colombia: fetch failed — %s", exc)
        await _log_sync_skipped("anh_co", f"fetch failed: {type(exc).__name__}")
        return 0

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        firma_ms = props.get("FECHA_FIRM")
        rows.append({
            "source":        "anh_co",
            "source_id":     str(props.get("CONTRAT_ID") or ""),
            "activity_type": "oil_gas",
            "name":          props.get("CONTRATO_N") or props.get("AREA_NOMBR"),
            "operator":      props.get("OPERADOR"),
            "country":       "COL",
            "status":        (props.get("ESTAD_AREA") or "active").lower(),
            "awarded_date":  datetime.fromtimestamp(firma_ms / 1000) if firma_ms else None,
            "expires_date":  None,
            "portal_url":    "https://www.anh.gov.co/Paginas/GeoVisor.aspx",
            "attributes":    {k: v for k, v in props.items()},
            "geom":          geom,
        })

    if not rows:
        log.warning("anh-colombia: no features returned")
        await _log_sync_skipped("anh_co", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "anh_co")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("anh_co", inserted, total)
    log.info("anh-colombia: %d new / %d total", inserted, total)
    return inserted


# ── Tier-2 expansion: Trinidad & Tobago, Ireland, Peru, Ghana, Guyana ────────

async def sync_meei_trinidad() -> int:
    """Fetch T&T offshore concession blocks from MEEA ArcGIS Online (Concession_Blocks_2026).

    Source: services9.arcgis.com/4Gq7iUQgqdKup4MU/.../Concession_Blocks_2026/FeatureServer/0
    Owner: sfranklin_MEEA (Ministry of Energy and Energy Affairs, Trinidad & Tobago).
    Filter: Block_Type='Offshore' — excludes ~40 onshore blocks (96 offshore remain).
    Fields: Block_ID (id), Block_Name (name), Parties (operator), Status,
            Effec_Date (awarded), Term_Date (expires), License_Ty (licence type).
    """
    TT_URL = (
        "https://services9.arcgis.com/4Gq7iUQgqdKup4MU/arcgis/rest/services/"
        "Concession_Blocks_2026/FeatureServer/0/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(
            TT_URL, out_fields="*",
            extra_params={"where": "Block_Type='Offshore'"},
        )
    except Exception as exc:
        log.warning("meei-trinidad: fetch failed — %s", exc)
        await _log_sync_skipped("meei_tt", f"fetch failed: {type(exc).__name__}")
        return 0

    def _ms_to_date(ms):
        if ms is None:
            return None
        try:
            return datetime.utcfromtimestamp(int(ms) / 1000).date().isoformat()
        except Exception:
            return None

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        rows.append({
            "source":        "meei_tt",
            "source_id":     str(props.get("Block_ID") or props.get("FID") or ""),
            "activity_type": "oil_gas",
            "name":          props.get("Block_Name"),
            "operator":      props.get("Short_Part") or props.get("Parties"),
            "country":       "TTO",
            "status":        (props.get("Status") or "active").lower(),
            "awarded_date":  _ms_to_date(props.get("Effec_Date")),
            "expires_date":  _ms_to_date(props.get("Term_Date")),
            "portal_url":    "https://www.energy.gov.tt/resource-management/",
            "attributes":    {k: v for k, v in props.items()},
            "geom":          geom,
        })

    if not rows:
        log.warning("meei-trinidad: no features returned")
        await _log_sync_skipped("meei_tt", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "meei_tt")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("meei_tt", inserted, total)
    log.info("meei-trinidad: %d new / %d total", inserted, total)
    return inserted


async def sync_pad_ireland() -> int:
    """Fetch Irish petroleum exploration and production authorisations from IPAS ArcGIS.

    Source: services2.arcgis.com/9g6TNz2FCkMRX6Tw/.../IPAS_Petroleum_Exploration.../FeatureServer/0
    Owner: GSRO (Geological Survey Ireland Resource Operations / DCCAE Petroleum Affairs Division).
    Layer 0 = Active Authorisations. Fields: AUTHORISAT (licence id), OPERATOR, TYPE, SUBTYPE,
    STATUS, START_DATE (epoch ms), END_DATE (epoch ms).
    """
    IE_URL = (
        "https://services2.arcgis.com/9g6TNz2FCkMRX6Tw/arcgis/rest/services/"
        "IPAS_Petroleum_Exploration_and_Production_Authorisations/FeatureServer/0/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(IE_URL, out_fields="*")
    except Exception as exc:
        log.warning("pad-ireland: fetch failed — %s", exc)
        await _log_sync_skipped("pad_ie", f"fetch failed: {type(exc).__name__}")
        return 0

    def _ms_to_date(ms):
        if ms is None:
            return None
        try:
            return datetime.utcfromtimestamp(int(ms) / 1000).date().isoformat()
        except Exception:
            return None

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        auth = str(props.get("AUTHORISAT") or props.get("OBJECTID") or "")
        rows.append({
            "source":        "pad_ie",
            "source_id":     auth,
            "activity_type": "oil_gas",
            "name":          auth or None,
            "operator":      props.get("OPERATOR"),
            "country":       "IRL",
            "status":        (props.get("STATUS") or "active").lower(),
            "awarded_date":  _ms_to_date(props.get("START_DATE")),
            "expires_date":  _ms_to_date(props.get("END_DATE")),
            "portal_url":    "https://www.gov.ie/en/publication/63e171-oil-and-gas-exploration-production-data/",
            "attributes":    {k: v for k, v in props.items()},
            "geom":          geom,
        })

    if not rows:
        log.warning("pad-ireland: no features returned")
        await _log_sync_skipped("pad_ie", "source returned no features with geometry")
        return 0

    if not rows:
        log.warning("pad-ireland: no features returned")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "pad_ie")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("pad_ie", inserted, total)
    log.info("pad-ireland: %d new / %d total", inserted, total)
    return inserted


async def sync_perupetro() -> int:
    """Fetch Peruvian offshore petroleum blocks from PERUPETRO via INGEMMET ArcGIS Hub.

    Source: services1.arcgis.com/IOnDXYLCAWAfoO54/.../Lote_Petroleros_Enero_2019_PERUPETRO/FeatureServer/0
    Filter: UBICACION='ZOCALO' (continental shelf / offshore) — 12 of ~100 blocks.
    Fields: OBJECTID (id), NOMB_LOTE (name), CIA (operator/company),
            UBICACION (basin/location), F_EFECTIVA (effective date),
            F_SUSCRIPC (subscription date), TIPO_CONTR (contract type).
    """
    PERU_URL = (
        "https://services1.arcgis.com/IOnDXYLCAWAfoO54/arcgis/rest/services/"
        "Lote_Petroleros_Enero_2019_PERUPETRO/FeatureServer/0/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(
            PERU_URL, out_fields="*",
            extra_params={"where": "UBICACION='ZOCALO'"},
        )
    except Exception as exc:
        log.warning("perupetro: fetch failed — %s", exc)
        await _log_sync_skipped("perupetro_pe", f"fetch failed: {type(exc).__name__}")
        return 0

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        date_val = props.get("F_EFECTIVA") or props.get("F_SUSCRIPC")
        awarded = None
        if date_val:
            try:
                awarded = datetime.utcfromtimestamp(int(date_val) / 1000).date().isoformat()
            except Exception:
                awarded = str(date_val)[:10] if date_val else None
        rows.append({
            "source":        "perupetro_pe",
            "source_id":     str(props.get("OBJECTID") or props.get("FID") or ""),
            "activity_type": "oil_gas",
            "name":          props.get("NOMB_LOTE"),
            "operator":      props.get("CIA"),
            "country":       "PER",
            "status":        "active",
            "awarded_date":  awarded,
            "expires_date":  None,
            "portal_url":    "https://www.perupetro.com.pe/",
            "attributes":    {k: v for k, v in props.items()},
            "geom":          geom,
        })

    if not rows:
        log.warning("perupetro: no features returned")
        await _log_sync_skipped("perupetro_pe", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "perupetro_pe")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("perupetro_pe", inserted, total)
    log.info("perupetro: %d new / %d total", inserted, total)
    return inserted


async def sync_petrocom_ghana() -> int:
    """Fetch Ghanaian offshore licensed blocks from GNPC ArcGIS Online.

    Source: services3.arcgis.com/P11fCRq9Db4CjHMS/.../OFFSHORE_RESOURCES_.../FeatureServer/96
    Owner: USER_GNPC_AGOL (Ghana National Petroleum Corporation — state entity).
    ~17 active petroleum agreements, all offshore.
    Fields: Name, Company (operator), GHID_licen (licence id), Status,
            Start_date (awarded, epoch ms), End_date (expires, epoch ms).
    """
    GH_URL = (
        "https://services3.arcgis.com/P11fCRq9Db4CjHMS/arcgis/rest/services/"
        "OFFSHORE_RESOURCES___HUB_CONCEPT_WFL1/FeatureServer/96/query"
    )
    rows: list[dict] = []
    try:
        features = await fetch_arcgis_features_url(GH_URL, out_fields="*")
    except Exception as exc:
        log.warning("petrocom-ghana: fetch failed — %s", exc)
        await _log_sync_skipped("petrocom_gh", f"fetch failed: {type(exc).__name__}")
        return 0

    def _ms_to_date(ms):
        if ms is None:
            return None
        try:
            return datetime.utcfromtimestamp(int(ms) / 1000).date().isoformat()
        except Exception:
            return None

    for f in features:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        if not geom:
            continue
        rows.append({
            "source":        "petrocom_gh",
            "source_id":     str(props.get("GHID_licen") or props.get("FID") or props.get("OBJECTID") or ""),
            "activity_type": "oil_gas",
            "name":          props.get("Name") or props.get("Alias"),
            "operator":      props.get("Company"),
            "country":       "GHA",
            "status":        (props.get("Status") or "active").lower(),
            "awarded_date":  _ms_to_date(props.get("Start_date")),
            "expires_date":  _ms_to_date(props.get("End_date")),
            "portal_url":    "https://petrocom.gov.gh/maps/",
            "attributes":    {k: v for k, v in props.items()},
            "geom":          geom,
        })

    if not rows:
        log.warning("petrocom-ghana: no features returned")
        await _log_sync_skipped("petrocom_gh", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "petrocom_gh")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("petrocom_gh", inserted, total)
    log.info("petrocom-ghana: %d new / %d total", inserted, total)
    return inserted


async def sync_pmp_guyana() -> int:
    """Fetch Guyanese offshore petroleum blocks from the official PMP shapefile.

    Source: petroleum.gov.gy/wp-content/uploads/2024/10/Auction-Blocks.zip
    Publisher: Petroleum Management Programme, Guyana — official government body.
    22 blocks (Apr 2026). Fields: Id (source_id), Name (block name), License (parties).
    All blocks are offshore (Guyana has no onshore licensing programme).
    """
    ZIP_URL = "https://petroleum.gov.gy/wp-content/uploads/2024/10/Auction-Blocks.zip"
    rows: list[dict] = []
    try:
        import shapefile as _shapefile
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            r = await _get_with_retry(client, ZIP_URL, label="zip download")
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            names = z.namelist()
            shp_name = next((n for n in names if n.lower().endswith(".shp")), None)
            if not shp_name:
                log.warning("pmp-guyana: no .shp in zip")
                await _log_sync_skipped("pmp_gy", "no .shp file found in downloaded zip")
                return 0
            base = shp_name[:-4]
            shp_bytes = io.BytesIO(z.read(shp_name))
            dbf_bytes = io.BytesIO(z.read(base + ".dbf"))
            sf = _shapefile.Reader(shp=shp_bytes, dbf=dbf_bytes)
            fields = [fld[0] for fld in sf.fields[1:]]
            for idx, sr in enumerate(sf.shapeRecords()):
                props = dict(zip(fields, sr.record))
                try:
                    geom = sr.shape.__geo_interface__
                except Exception:
                    continue
                if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
                    continue
                # DBF field names vary by shapefile version; fall back to row index
                src_id = str(props.get("Id") or props.get("ID") or props.get("id") or props.get("OBJECTID") or idx + 1)
                rows.append({
                    "source":        "pmp_gy",
                    "source_id":     src_id,
                    "activity_type": "oil_gas",
                    "name":          props.get("Name") or props.get("NAME") or props.get("name"),
                    "operator":      props.get("License") or props.get("LICENSE") or props.get("license"),
                    "country":       "GUY",
                    "status":        "active",
                    "awarded_date":  None,
                    "expires_date":  None,
                    "portal_url":    "https://petroleum.gov.gy/oil-blocks/",
                    "attributes":    {k: str(v) if v is not None else None for k, v in props.items()},
                    "geom":          geom,
                })
    except Exception as exc:
        log.warning("pmp-guyana: failed — %s", exc)
        await _log_sync_skipped("pmp_gy", f"fetch failed: {type(exc).__name__}")
        return 0

    if not rows:
        log.warning("pmp-guyana: no features returned")
        await _log_sync_skipped("pmp_gy", "source returned no features with geometry")
        return 0

    async with db.pool.acquire() as conn:
        inserted = await offshore_upsert(conn, rows)
        await offshore_tag_sovereign(conn, "pmp_gy")
        total = await conn.fetchval("SELECT COUNT(*) FROM offshore_activities")

    clear_offshore_tile_cache()
    await _log_sync("pmp_gy", inserted, total)
    log.info("pmp-guyana: %d new / %d total", inserted, total)
    return inserted
