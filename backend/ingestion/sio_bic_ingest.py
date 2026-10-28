# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SIO-BIC catalogue: parser for a STATIC snapshot of the collection's CSV export.

Source: https://sioapps.ucsd.edu/collections/bi/ (the export behind its search page).
⛔ Never fetched automatically. On 2026-10-27 SIO-BIC (C. Seid, after Scripps IT
ticket #152993) declined automated access: the campus Cloudflare Turnstile on
sioapps.ucsd.edu is intentional. They allowed a static version made from a download
"like any user". So the owner downloads the export by hand in a browser a few times
a year and copies it to SNAPSHOT_FILE on the VPS; this module only reads that file.
It makes no network request, and must never be given one or a Turnstile workaround.
The snapshot date shown in the legend lives in public/locales/*/legend.json.

Snapshot: /var/cache/sio-bic/BIC_all.csv (SIO_BIC_CACHE_DIR overrides the directory).
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
import csv
import io
import re
from datetime import date
from pathlib import Path

SNAPSHOT_DIR = Path(os.getenv("SIO_BIC_CACHE_DIR", "/var/cache/sio-bic"))
SNAPSHOT_FILE = SNAPSHOT_DIR / "BIC_all.csv"

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
    """The manually downloaded snapshot. No network: see the module docstring."""
    if not SNAPSHOT_FILE.exists():
        raise RuntimeError(f"sio-bic snapshot missing: {SNAPSHOT_FILE} (copied by hand, never fetched)")
    data = SNAPSHOT_FILE.read_bytes()
    # A Turnstile/HTML page saved as CSV must not reach the parser: it would parse
    # to zero rows and the sync would report a "successful" empty catalogue.
    head = data[:4096].lstrip()
    if head[:1] == b"<" or b"Bot verification" in head or b"Catalog ID" not in head:
        raise RuntimeError(f"sio-bic snapshot is not the collection CSV: {SNAPSHOT_FILE}")
    return data
