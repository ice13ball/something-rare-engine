# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Download all Confirmed KBAs from BirdLife ArcGIS Feature Server
and import into PostGIS key_biodiversity_areas table — page by page.

Usage: cd backend && source .venv/bin/activate && python3 scripts/download_kbas.py
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
import urllib.request
import urllib.parse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
log = logging.getLogger("kba_download")

FEATURE_SERVER = (
    "https://maps.birdlife.org/server/rest/services/Hosted/Confirmed_KBAs/FeatureServer/0"
)
PAGE_SIZE = 1000  # smaller pages = less RAM
OGR2OGR = "/usr/bin/ogr2ogr"
PG_CONN = f"PG:host=localhost dbname=abyssal user=abyssal_user password={os.environ.get('PGPASSWORD', 'CHANGE_ME')}"


def query(params: dict) -> dict:
    """Query ArcGIS Feature Server."""
    url = f"{FEATURE_SERVER}/query?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "AbyssalClaims/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())


def get_total() -> int:
    return query({"where": "1=1", "returnCountOnly": "true", "f": "json"})["count"]


def fetch_and_import_page(offset: int) -> int:
    """Fetch one page of GeoJSON, write to temp file, import via ogr2ogr."""
    params = {
        "where": "1=1",
        "outFields": "intname,country,area,kbastatus",
        "resultOffset": str(offset),
        "resultRecordCount": str(PAGE_SIZE),
        "f": "geojson",
    }
    data = query(params)
    features = data.get("features", [])
    if not features:
        return 0

    # Write page to temp file
    tmp = tempfile.NamedTemporaryFile(suffix=".geojson", delete=False, mode="w")
    json.dump({"type": "FeatureCollection", "features": features}, tmp)
    tmp.close()

    # Import with ogr2ogr — map fields to match table schema
    # ogr2ogr auto-names the layer from the GeoJSON "name" property or filename
    layer_name = os.path.splitext(os.path.basename(tmp.name))[0]
    cmd = [
        OGR2OGR, "-f", "PostgreSQL", PG_CONN, tmp.name,
        "-nln", "key_biodiversity_areas",
        "-append",
        "-nlt", "MULTIPOLYGON",
        "-lco", "GEOMETRY_NAME=geom",
        "-t_srs", "EPSG:4326",
        "--config", "PG_USE_COPY", "YES",
        "-sql", (
            f'SELECT intname AS site_name, country, kbastatus AS status, '
            f'area AS area_km2 '
            f'FROM "{layer_name}"'
        ),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    os.unlink(tmp.name)

    if result.returncode != 0:
        log.error("ogr2ogr failed (offset %d): %s", offset, result.stderr)
        return 0

    return len(features)


def main():
    total = get_total()
    log.info("Total KBA features: %d, pages: %d", total, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    imported = 0
    offset = 0
    page = 0
    while offset < total:
        page += 1
        log.info("Page %d (offset %d / %d)...", page, offset, total)
        count = fetch_and_import_page(offset)
        if count == 0:
            log.warning("Empty page at offset %d, stopping", offset)
            break
        imported += count
        log.info("  imported %d (total: %d / %d)", count, imported, total)
        offset += PAGE_SIZE

    log.info("Done! Imported %d KBA polygons", imported)


if __name__ == "__main__":
    main()
