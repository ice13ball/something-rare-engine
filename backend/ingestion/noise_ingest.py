#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Ingest ICES impulsive noise (PBD) and EMODnet continuous SPL into noise_cells table.
Run standalone: cd ~/something-rare/backend && source .venv/bin/activate && python3 ingestion/noise_ingest.py
"""
import asyncio
import os
import asyncpg
import httpx
import json
import math
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

DB_URL = os.environ.get("DATABASE_URL", "postgresql://abyssal_user:CHANGE_ME@localhost/abyssal")

ICES_WFS = (
    "https://gis.ices.dk/gis/services/OSPAR_CEMP/MapServer/WFSServer"
    "?service=WFS&version=2.0.0&request=GetFeature"
    "&typeName=OSPAR_CEMP:CEMP_PulseBlockDays&outputFormat=application/json"
    "&count=5000"
)

# ⚠️ THIS DATASET HAS EXACTLY ONE STATION. Not one after our filtering — one in the
# dataset. Verified at the source 2026-09-08: the query below returns 1,576,548 rows
# (56 MB), and `?longitude,latitude&distinct()` with NO time filter returns a single
# position, off Galicia at roughly -8.78, 42.63. So `noise_cells` holding one row for
# source `emodnet` is CORRECT, not a broken ingest — do not "fix" it. What it means is
# that the continuous-SPL input to the noise-risk layer is one hydrophone, not a
# coverage surface, and whether that input earns its 56 MB download is a question for
# the layer's design rather than for this parser.
EMODNET_ERDDAP = (
    "https://erddap.emodnet-physics.eu/erddap/tabledap/EP_ERD_INT_UWN_NAT.json"
    "?longitude,latitude,TotalSPL&time>=2023-01-01"
)

# EMODnet impulsive noise (Pulse Block Days) — OSPAR/HELCOM area, 2014-2022
# Uses ICES sub-rectangle identifiers; we decode to lat/lon via the ICES grid spec
EMODNET_INER_CSV = (
    "https://erddap.emodnet-physics.eu/erddap/tabledap/EP_UWN_INER.csv"
    "?pulsedays,subsquare,year"
)

GRID_DEG = 1.0  # 1° grid cells

# 180 is a normalisation divisor this platform chose, not a documented ICES
# reporting ceiling — no such ceiling is published. Production impulsive_pbd
# values observed range from 1 to 353, so values above 180 saturate at 1.0
# after normalisation; that flattens roughly the upper half of the observed
# range to the maximum. If a real ICES-documented ceiling is ever found and
# verified, cite it here with a URL and the date checked.
PBD_DAYS_PER_YEAR = 180.0

# EMODnet continuous SPL is reported in dB re 1 uPa. The 80 dB floor and 80 dB
# span below are the range this platform chose for display, NOT a property of
# the source. They are a presentation decision and are documented as such in
# docs/methods/data-passthrough.md.
SPL_REF_DB = 80.0
SPL_SPAN_DB = 80.0


def snap(val: float, step: float = GRID_DEG) -> float:
    return math.floor(val / step) * step


def cell_key(lon: float, lat: float, source: str) -> str:
    return f"{snap(lon)}_{snap(lat)}_{source}"


async def ingest_ices(conn: asyncpg.Connection, client: httpx.AsyncClient):
    log.info("Fetching ICES PBD data...")
    try:
        r = await client.get(ICES_WFS, timeout=60)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log.warning("ICES fetch failed: %s", e)
        return

    # Aggregate to 1° grid: take max PBD per cell
    cells: dict[str, dict] = {}
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        geom  = feat.get("geometry", {})
        pbd   = props.get("PBD") or props.get("pbd") or props.get("PulseBlockDays")
        if pbd is None or not geom:
            continue
        coords = geom.get("coordinates", [])
        if geom["type"] == "Polygon":
            flat = coords[0]
            lon = sum(c[0] for c in flat) / len(flat)
            lat = sum(c[1] for c in flat) / len(flat)
        elif geom["type"] == "Point":
            lon, lat = coords[0], coords[1]
        else:
            continue
        key = cell_key(lon, lat, "ices")
        if key not in cells or pbd > cells[key]["pbd"]:
            cells[key] = {"lon": snap(lon), "lat": snap(lat), "pbd": float(pbd)}

    log.info("ICES: %d grid cells after aggregation", len(cells))

    for key, c in cells.items():
        pbd_norm = min(1.0, c["pbd"] / PBD_DAYS_PER_YEAR)
        await conn.execute("""
            INSERT INTO noise_cells (geom, lon, lat, cell_key, impulsive_pbd, pbd_norm, source, region, updated_at)
            VALUES (ST_SetSRID(ST_MakePoint($1,$2),4326), $1, $2, $3, $4, $5, 'ices', 'north_atlantic', NOW())
            ON CONFLICT (cell_key) DO UPDATE SET
                impulsive_pbd = EXCLUDED.impulsive_pbd,
                pbd_norm      = EXCLUDED.pbd_norm,
                updated_at    = NOW()
        """, c["lon"], c["lat"], key, c["pbd"], pbd_norm)

    log.info("ICES: upserted %d cells", len(cells))


def decode_subsquare(sq: str) -> tuple[float, float] | None:
    """
    Decode ICES sub-rectangle code (e.g. '07C09') to (lon, lat) centroid.
    Format: LLCSS — LL=lat code, C=lon letter, SS=sub-position (01-100).
    Lat code 01 = 36-36.5°N, +0.5° per step.
    Lon letter: A=0-1°E, B=0-1°W, C=1-2°W, D=2-3°W, ... (each letter = 1° westward from 0°E).
    Sub 01-100 row-major from SW corner in a 10×10 grid (0.05°lat × 0.1°lon each).
    """
    try:
        lat_code = int(sq[:2])
        lon_letter = sq[2]
        sub_num = int(sq[3:])
        lat_sw = 36.0 + (lat_code - 1) * 0.5
        col_idx = ord(lon_letter) - ord("A")
        lon_sw = -col_idx  # A=0°E→0, B→-1°W, C→-2°W, etc.
        row = math.ceil(sub_num / 10)
        col = ((sub_num - 1) % 10) + 1
        lat = lat_sw + (row - 1) * 0.05 + 0.025
        lon = lon_sw + (col - 1) * 0.1 + 0.05
        return round(lon, 3), round(lat, 3)
    except (ValueError, IndexError):
        return None


def aggregate_emodnet_iner_rows(lines: list[str]) -> dict[str, dict]:
    """Aggregate EMODnet INER CSV data rows (no header/units rows) to a 1°
    grid: max pulsedays per cell, PLUS the year the max came from and the
    full year span of every row considered for that cell.

    Column order is fixed by EMODNET_INER_CSV: pulsedays, subsquare, year.

    - A row with a blank subsquare is skipped (the source's own gap).
    - A row with a missing/unparseable year still contributes its pulsedays
      to the max; it just contributes no year to pbd_year or the span —
      a missing year stays missing, never substituted.
    - pbd_year_min/pbd_year_max widen to cover every row seen for the cell
      (whether or not that row's pulsedays won the max), so a reader can
      see how wide a pool the maximum was taken over.
    """
    cells: dict[str, dict] = {}
    for line in lines:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            pbd = float(parts[0])
            sq = parts[1].strip()
        except (ValueError, IndexError):
            continue
        if not sq:
            continue

        year: int | None = None
        if len(parts) > 2:
            raw_year = parts[2].strip()
            if raw_year:
                try:
                    year = int(raw_year)
                except ValueError:
                    year = None

        coords = decode_subsquare(sq)
        if not coords:
            continue
        lon, lat = coords
        key = cell_key(lon, lat, "emodnet_iner")

        cell = cells.get(key)
        if cell is None:
            cells[key] = {
                "lon": snap(lon), "lat": snap(lat), "pbd": pbd,
                "pbd_year": year, "pbd_year_min": year, "pbd_year_max": year,
            }
            continue

        if pbd > cell["pbd"]:
            cell["pbd"] = pbd
            cell["pbd_year"] = year
        if year is not None:
            if cell["pbd_year_min"] is None or year < cell["pbd_year_min"]:
                cell["pbd_year_min"] = year
            if cell["pbd_year_max"] is None or year > cell["pbd_year_max"]:
                cell["pbd_year_max"] = year

    return cells


async def ingest_emodnet_iner(conn: asyncpg.Connection, client: httpx.AsyncClient):
    """Ingest EMODnet impulsive noise (PBD) via EP_UWN_INER — OSPAR/HELCOM area."""
    log.info("Fetching EMODnet INER impulsive noise data...")
    try:
        r = await client.get(EMODNET_INER_CSV, timeout=120)
        r.raise_for_status()
    except Exception as e:
        log.warning("EMODnet INER fetch failed: %s", e)
        return

    lines = r.text.splitlines()
    if len(lines) < 3:
        log.warning("EMODnet INER: no data returned")
        return

    # Skip header and units row; take max PBD per 1° grid cell across all years
    cells = aggregate_emodnet_iner_rows(lines[2:])

    log.info("EMODnet INER: %d grid cells after aggregation", len(cells))

    for key, c in cells.items():
        pbd_norm = min(1.0, c["pbd"] / PBD_DAYS_PER_YEAR)
        await conn.execute("""
            INSERT INTO noise_cells (
                geom, lon, lat, cell_key, impulsive_pbd, pbd_norm,
                pbd_year, pbd_year_min, pbd_year_max, source, region, updated_at
            )
            VALUES (
                ST_SetSRID(ST_MakePoint($1,$2),4326), $1, $2, $3, $4, $5,
                $6, $7, $8, 'emodnet_iner', 'ospar_helcom', NOW()
            )
            ON CONFLICT (cell_key) DO UPDATE SET
                impulsive_pbd = EXCLUDED.impulsive_pbd,
                pbd_norm      = EXCLUDED.pbd_norm,
                pbd_year      = EXCLUDED.pbd_year,
                pbd_year_min  = EXCLUDED.pbd_year_min,
                pbd_year_max  = EXCLUDED.pbd_year_max,
                updated_at    = NOW()
        """, c["lon"], c["lat"], key, c["pbd"], pbd_norm,
             c["pbd_year"], c["pbd_year_min"], c["pbd_year_max"])

    log.info("EMODnet INER: upserted %d cells", len(cells))


async def ingest_emodnet(conn: asyncpg.Connection, client: httpx.AsyncClient):
    log.info("Fetching EMODnet SPL stations...")
    try:
        r = await client.get(EMODNET_ERDDAP, timeout=60)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        log.warning("EMODnet fetch failed: %s", e)
        return

    cols  = payload.get("table", {}).get("columnNames", [])
    rows  = payload.get("table", {}).get("rows", [])
    if not cols or not rows:
        log.warning("EMODnet: no data returned")
        return

    lon_i   = cols.index("longitude") if "longitude" in cols else None
    lat_i   = cols.index("latitude")  if "latitude"  in cols else None
    spl_i   = cols.index("TotalSPL") if "TotalSPL" in cols else None

    if any(i is None for i in [lon_i, lat_i, spl_i]):
        log.warning("EMODnet: missing expected columns, got: %s", cols)
        return

    cells: dict[str, dict] = {}
    for row in rows:
        try:
            lon = float(row[lon_i])
            lat = float(row[lat_i])
            spl = float(row[spl_i])
        except (TypeError, ValueError):
            continue
        key = cell_key(lon, lat, "emodnet")
        if key not in cells or spl > cells[key]["spl"]:
            cells[key] = {"lon": snap(lon), "lat": snap(lat), "spl": spl}

    log.info("EMODnet: %d grid cells after aggregation", len(cells))

    for key, c in cells.items():
        spl_norm = min(1.0, max(0.0, (c["spl"] - SPL_REF_DB) / SPL_SPAN_DB))
        await conn.execute("""
            INSERT INTO noise_cells (geom, lon, lat, cell_key, continuous_spl, spl_norm, source, updated_at)
            VALUES (ST_SetSRID(ST_MakePoint($1,$2),4326), $1, $2, $3, $4, $5, 'emodnet', NOW())
            ON CONFLICT (cell_key) DO UPDATE SET
                continuous_spl = EXCLUDED.continuous_spl,
                spl_norm       = EXCLUDED.spl_norm,
                updated_at     = NOW()
        """, c["lon"], c["lat"], key, c["spl"], spl_norm)

    log.info("EMODnet: upserted %d cells", len(cells))


async def main():
    conn = await asyncpg.connect(DB_URL)
    async with httpx.AsyncClient() as client:
        await ingest_ices(conn, client)
        await ingest_emodnet_iner(conn, client)
        await ingest_emodnet(conn, client)
    total = await conn.fetchval("SELECT COUNT(*) FROM noise_cells")
    log.info("Done. noise_cells total: %d", total)
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
