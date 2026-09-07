# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SIO-BIC catalogue CSV bulk fetcher.

Source: https://sioapps.ucsd.edu/collections/bi/api/export/
Per Charlotte Seid (Scripps, 2026-05-04): cached scrapes only.
The /api/export/?taxa=all endpoint returns the full catalogue (~98k rows) as a single
CSV — no HTML scraping, no rate-limit semaphore (one request total).

Caching: 7-day on-disk cache at /var/cache/sio-bic/BIC_all.csv (mtime check).
Filter: lat IS NOT NULL AND lon IS NOT NULL. No depth floor — shallow records
(50–500 m continental shelf) are relevant for offshore-claim monitoring density.

CSV quirk: data rows ship 49-50 fields vs the 47-column header (duplicate
signed lat/lon + a trailing boolean appended by the Django export). DictReader
accesses columns by name so this doesn't affect us — but `Image ID` (always
empty) and `Photo` (misaligned artifact, contains lat floats) are intentionally
dropped from the schema. Probed 2026-05-04: 13/13 HTML detail pages had no
specimen images.
"""
import os
import asyncio
import csv
import io
import re
import shutil
import time
from datetime import date, timedelta
from pathlib import Path

CACHE_DIR = Path(os.getenv("SIO_BIC_CACHE_DIR", "/var/cache/sio-bic"))
CACHE_FILE = CACHE_DIR / "BIC_all.csv"
CACHE_TTL = timedelta(days=7)
EXPORT_URL = "https://sioapps.ucsd.edu/collections/bi/api/export/?taxa=all"
from ingestion import USER_AGENT

_KV_RE = re.compile(r"\s*([a-zA-Z_]+)\s*=\s*([^,]+?)\s*(?:,|$)")


def _parse_collection_type(s: str) -> dict[str, str]:
    """Parse 'type=whole, fixative=EtOH 95%, ...' into a dict."""
    return {m.group(1): m.group(2) for m in _KV_RE.finditer(s or "")}


def _signed(value: str | None, direction: str | None) -> float | None:
    """Combine '22.5323' + 'S' → -22.5323. Returns None if either missing."""
    if not value or not direction:
        return None
    try:
        v = float(value)
    except ValueError:
        return None
    return -abs(v) if direction.upper() in ("S", "W") else abs(v)


def _safe_int(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _safe_float(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _safe_date(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            from datetime import datetime
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


async def fetch_sio_bic_records() -> list[dict]:
    """Return list of canonical-shape dicts ready for upsert.

    Skips rows with missing begin lat/lon or begin_depth_m < 200.
    """
    csv_bytes = await _fetch_or_cache()
    out: list[dict] = []
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8", errors="replace")))
    for row in reader:
        lat = _signed(row.get("Begin Latitude"), row.get("Beg Lat Dir"))
        lon = _signed(row.get("Begin Longitude"), row.get("Lon Dir"))
        if lat is None or lon is None:
            continue
        begin_depth = _safe_float(row.get("Begin Depth"))
        ct = _parse_collection_type(row.get("Collection Type ID", ""))
        catalog_id_raw = _safe_int(row.get("Catalog ID"))
        if catalog_id_raw is None:
            continue
        out.append({
            "catalog_id":         catalog_id_raw,
            "higher_taxa_code":   row.get("Higher Taxa Code") or None,
            "catalog_no":         row.get("Catalog #") or None,
            "phylum":             row.get("Phylum") or None,
            "class_":             row.get("Class") or None,
            "order_":             row.get("Order") or None,
            "family":             row.get("Family") or None,
            "genus":              row.get("Genus") or None,
            "species":            row.get("Species") or None,
            "authority":          row.get("Verbatum Authority") or None,
            "identifier":         row.get("Identifier") or None,
            "type_status":        row.get("Type Status") or None,
            "count":              _safe_int(row.get("Count")),
            "collection_type_raw": row.get("Collection Type ID") or None,
            "specimen_type":      ct.get("type"),
            "fixative":           ct.get("fixative"),
            "preservative":       ct.get("preservative"),
            "storage_location":   ct.get("location"),
            "reference_id":       row.get("Reference ID") or None,
            "loan_id":            row.get("Loan ID") or None,
            "gift_id":            row.get("Gift ID") or None,
            "catalog_notes":      row.get("Catalog Notes") or None,
            "genbank":            row.get("Genback #") or None,
            "accession_no":       row.get("Acc #") or None,
            "accession_id":       row.get("Accession ID") or None,
            "accession_date":     _safe_date(row.get("Accession Date")),
            "station":            row.get("Station #") or None,
            "locality":           row.get("Locality") or None,
            "country":            row.get("Country") or None,
            "ocean":              row.get("Ocean") or None,
            "lat":                lat,
            "lon":                lon,
            "end_lat":            _signed(row.get("End Latitude"), row.get("End Lat Dir")),
            "end_lon":            _signed(row.get("End Longitude"), row.get("End Lon Dir")),
            "begin_depth_m":      begin_depth,
            "end_depth_m":        _safe_float(row.get("End Depth")),
            # No fallback. An empty cell means the source declared no unit, and
            # NULL says exactly that. Defaulting to "m" made 83,448 rows agree
            # perfectly and told us nothing about which of them the source had
            # actually labelled. See docs/methods/data-passthrough.md.
            "depth_unit":         row.get("Depth Unit") or None,
            "collection_date":    _safe_date(row.get("Collection Date")),
            "collection_time":    row.get("Collection Time") or None,
            "gear":               row.get("Gear") or None,
            "ship":               row.get("Ship") or None,
            "collector":          row.get("Collector") or None,
            "remarks":            row.get("Remarks") or None,
        })
    return out


async def _fetch_or_cache() -> bytes:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if (
        CACHE_FILE.exists()
        and (time.time() - CACHE_FILE.stat().st_mtime) < CACHE_TTL.total_seconds()
    ):
        return CACHE_FILE.read_bytes()
    # Download via curl -4, NOT httpx: this VPS's IPv6 path to sioapps.ucsd.edu is
    # black-holed, and httpx stalls the full timeout with no Happy-Eyeballs fallback
    # (the /admin/sync/sio-bic task then hangs silently and never logs). curl races
    # v4/v6 and -4 forces IPv4. Absolute path because the abyssal-api systemd PATH is
    # venv-only (no /usr/bin). See infra_vps_ipv6_blackhole_curl. Download to a temp
    # file + atomic replace so a partial/interrupted download never poisons the cache.
    curl = shutil.which("curl") or "/usr/bin/curl"
    tmp = CACHE_FILE.with_name(CACHE_FILE.name + ".tmp")
    proc = await asyncio.create_subprocess_exec(
        curl, "-4", "-fsS", "-A", USER_AGENT,
        "--connect-timeout", "30", "--max-time", "900",
        "-o", str(tmp), EXPORT_URL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"sio-bic curl download failed (rc={proc.returncode}): "
            f"{stderr.decode('utf-8', 'replace')[:200]}"
        )
    tmp.replace(CACHE_FILE)
    return CACHE_FILE.read_bytes()
