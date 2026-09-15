# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""DwC-archive ingestion for the DeepData ANALYTICS tier (`deepdata_stations`).

This module is **TIER 2** in our DeepData architecture:
- TIER 1 = `deepdata_occurrences`, fetched via OBIS REST in `deepdata_ingest.py`.
  It is a 1:1 mirror of contractor submissions and is NEVER modified by us.
- TIER 2 = `deepdata_stations` (this module), aggregated from OBIS-hosted
  Darwin Core archives at `https://datasets.obis.org/hosted/isa/`.
  It is platform-derived analysis (sampling-station rollups). The UI labels
  it as such — it is not the contractor's own analysis.

The two tiers share semantics (`dataset_id`, `contractor_code`) but never
join on the wire — separation is by schema, not just UI badging.

Source identity / citation
--------------------------
Each DwC archive carries an `eml.xml` with the contractor's verbatim
citation, license, rights-holder and pubDate. We store these in
`deepdata_dwc_archives` and surface them on every station-detail panel.

Incremental sync
----------------
Archives are reissued infrequently (quarterly to annually). We compare
`ETag` + `Content-Length` headers from a HEAD probe against stored values
in `deepdata_dwc_archives`. Only changed/new archives get re-downloaded.
First run: ~200 MB / ~5 min. Steady state: 140 HEADs in ~5 s.

Failure isolation
-----------------
Each archive runs in its own try/except in the orchestrator. A bad zip
sets `parse_error` on its row but does not abort the rest of the run.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, Iterable

import httpx

from ingestion.deepdata_ingest import parse_contractor_code

log = logging.getLogger(__name__)

INDEX_URL = "https://datasets.obis.org/hosted/isa/index.html"
ARCHIVE_URL_TMPL = "https://datasets.obis.org/hosted/isa/{slug}/{slug}.zip"
HEAD_CONCURRENCY = 16  # parallel HEADs against the index — be polite


# ───────────────────────── Index discovery ──────────────────────────────

_SLUG_HREF_RE = re.compile(r'href="([a-z0-9_]+)/index\.html"', re.IGNORECASE)


async def list_remote_slugs(client: httpx.AsyncClient) -> list[str]:
    """Fetch the index page and return all archive slugs."""
    r = await client.get(INDEX_URL)
    r.raise_for_status()
    return sorted(set(_SLUG_HREF_RE.findall(r.text)))


# ───────────────────────── HEAD probe ──────────────────────────────────

async def head_probe(client: httpx.AsyncClient, slug: str) -> dict[str, Any]:
    """Return ETag/Last-Modified/Content-Length for a given archive.

    On HTTP errors returns a dict with `error` set; the caller treats this
    as "skip this archive in this run, retry next time".
    """
    url = ARCHIVE_URL_TMPL.format(slug=slug)
    try:
        r = await client.head(url, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        return {"slug": slug, "error": str(e)}
    return {
        "slug": slug,
        "etag": r.headers.get("etag"),
        "last_modified": _parse_http_date(r.headers.get("last-modified")),
        "content_length": int(r.headers.get("content-length") or 0),
    }


def _parse_http_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # RFC 7231 IMF-fixdate: "Mon, 20 Apr 2026 18:09:13 GMT"
        return datetime.strptime(s, "%a, %d %b %Y %H:%M:%S GMT")
    except ValueError:
        return None


# ───────────────────────── Archive download + parse ─────────────────────

async def fetch_archive(client: httpx.AsyncClient, slug: str) -> bytes:
    """Download a single .zip into memory."""
    url = ARCHIVE_URL_TMPL.format(slug=slug)
    r = await client.get(url)
    r.raise_for_status()
    return r.content


def parse_archive(slug: str, zip_bytes: bytes) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Open a DwC zip, return (archive_meta, list[station]).

    `archive_meta` carries citation/license/rights_holder/pub_date/etc.
    `stations` is one row per derived sampling deployment for `deepdata_stations`.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        if "occurrence.txt" not in names or "eml.xml" not in names:
            raise ValueError(f"{slug}: missing occurrence.txt or eml.xml in archive")
        eml_meta = _parse_eml(zf.read("eml.xml"))
        occurrences = list(_iter_occurrences(zf.read("occurrence.txt"), slug))
        # ⛔ Every archive ships this file and we had never opened one.
        # Measured across all 140 archives on 2026-09-15: 42 carry real rows
        # (1.7 MB in total) and 98 carry a header and nothing else. Reading it
        # is what turns "we don't hold these measurements" into a fact with a
        # size, instead of an absence nobody had looked at.
        m_count, m_types = _read_measurements(zf, names, slug)

    archive_meta = {
        "slug":             slug,
        "title":            eml_meta.get("title"),
        "citation":         eml_meta.get("citation"),
        "license":          eml_meta.get("license"),
        "rights_holder":    eml_meta.get("rights_holder"),
        "pub_date":         eml_meta.get("pub_date"),
        "occurrence_count": len(occurrences),
        # ⚠️ The measurement VALUES are deliberately not stored yet — every
        # row sampled so far is one type, "Relative abundance", and it belongs
        # against a species, not against a station aggregate. What is stored
        # is the inventory, so choosing to keep them later is a decision made
        # from numbers rather than from a guess.
        "measurement_count": m_count,
        "measurement_types": m_types,
    }

    stations = aggregate_stations(slug, archive_meta, occurrences)
    archive_meta["station_count"] = len(stations)
    return archive_meta, stations


# ───────────────────────── eml.xml parser ───────────────────────────────

# EML uses a default namespace; ElementTree handles this with prefix-stripping
# below. We tolerate either the official EML schema or the GBIF-flavoured one.

def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


# Placeholder values contractors submit when they have nothing meaningful.
# Treated as None — better empty than misleading.
_NA_SENTINELS = {"", "NA", "N/A", "n/a", "NULL", "null", "None", "Not Reported", "Unknown"}


def _meaningful(s: str | None) -> str | None:
    if s is None:
        return None
    s = s.strip()
    return None if s in _NA_SENTINELS else s


def _findtext(root: ET.Element, *names: str) -> str | None:
    """Return the text of the first matching local-name whose value isn't a
    placeholder sentinel ('NA', empty, etc.). Walks descendants in doc order."""
    target = set(names)
    for el in root.iter():
        if _strip_ns(el.tag) in target:
            txt = _meaningful(el.text)
            if txt:
                return txt
    return None


def _findtext_full(root: ET.Element, *names: str) -> str | None:
    """Like _findtext, but concatenates ALL descendant text — useful for
    elements like <intellectualRights> where the text lives in nested
    <para><ulink><citetitle>...</citetitle></ulink></para> markup."""
    target = set(names)
    for el in root.iter():
        if _strip_ns(el.tag) in target:
            # itertext yields text and tail of every descendant in document order.
            joined = " ".join(t.strip() for t in el.itertext() if t and t.strip())
            joined = _meaningful(joined)
            if joined:
                return joined
    return None


def _parse_eml(eml_bytes: bytes) -> dict[str, Any]:
    """Extract citation/license/rights/pubDate from an EML document.

    Tolerant — placeholder values ('NA', empty, etc.) become None rather
    than getting stored as literal junk.
    """
    try:
        root = ET.fromstring(eml_bytes)
    except ET.ParseError as e:
        log.warning("eml: parse failed (%s)", e)
        return {}

    title          = _findtext(root, "title")
    citation       = _findtext(root, "citation", "bibliographicCitation")
    # License text lives inside nested <para><ulink><citetitle>...</citetitle></ulink></para>
    # so we have to concatenate descendant text rather than read .text directly.
    license_text   = _findtext_full(root, "intellectualRights", "license")
    rights_holder  = _findtext(root, "organizationName", "rightsHolder")
    pub_date_str   = _findtext(root, "pubDate")
    pub_date       = _parse_iso_date(pub_date_str)

    return {
        "title":         title,
        "citation":      citation,
        "license":       license_text,
        "rights_holder": rights_holder,
        "pub_date":      pub_date,
    }


def _parse_iso_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ───────────────────────── occurrence.txt streaming ─────────────────────

# Single occurrence.txt files reach ~92 MB (NORI biology). csv.DictReader
# is line-by-line so we never hold the whole file as Python objects.

# The columns we keep. ISA's occurrence.txt publishes 52 (counted across all
# 140 archives, 2026-09-15); the rest are inventoried in _OCC_FIELDS_UNUSED
# below so that "we chose not to keep this" and "nobody ever looked at the
# header" stop being the same silence.
_OCC_FIELDS = (
    "id", "dataset_id", "occurrenceID", "eventID",
    "eventDate", "year",
    "minimumDepthInMeters", "maximumDepthInMeters",
    "decimalLatitude", "decimalLongitude",
    "coordinateUncertaintyInMeters",
    "locationID", "samplingProtocol",
    "scientificName", "phylum",
)

# ⛔ Without these, a field we DO depend on is indistinguishable from a field
# the archive stopped publishing: `row.get(k)` answers None either way. If ISA
# renamed `decimalLatitude`, `aggregate_stations` would skip every occurrence
# for want of coordinates and the archive would parse to zero stations —
# successfully, with no error anywhere.
_OCC_FIELDS_REQUIRED = frozenset({
    "id", "occurrenceID", "eventID", "decimalLatitude", "decimalLongitude",
    "scientificName",
})

# Every other column ISA publishes, with why we do not keep it. ⛔ A reason
# here must be something somebody checked; where it is not, the word is
# "nieustalone". The column list was read from the real archives on
# 2026-09-15, not from the Darwin Core specification.
_OCC_FIELDS_UNUSED: dict[str, str] = {
    # Quantitative — the strongest candidates if we ever want specimen counts
    # on a station. Not kept because deepdata_stations aggregates occurrences,
    # not individuals, and summing counts across species would be a number
    # with no meaning. A deliberate choice, not an oversight.
    "individualCount":     "would need a per-species home; station rows count occurrences",
    "organismQuantity":    "as individualCount; paired with organismQuantityType",
    "organismQuantityType": "unit for organismQuantity, useless without it",
    "occurrenceStatus":    "present/absent flag; every ISA row sampled is 'present'",
    # Taxonomy below phylum. top_species and top_phyla already carry the two
    # ranks the panel shows.
    "kingdom":    "one value across the whole dataset (Animalia/Chromista)",
    "class":      "rank between phylum and species; panel shows neither",
    "order":      "rank between phylum and species; the panel shows neither",
    "family":     "rank between phylum and species; the panel shows neither",
    "genus":      "carried inside scientificName already; no separate use",
    "taxonRank":  "rank of scientificName; the panel does not qualify names",
    "taxonomicStatus": "accepted/synonym; we do not resolve synonymy here",
    "taxonRemarks":    "free text, per record",
    "taxonID":         "internal to the archive",
    "scientificNameID": "LSID; WoRMS resolution happens on the OBIS-REST tier",
    # Identification provenance
    "identificationID": "internal to the archive",
    "typeStatus":       "holotype/paratype; nieustalone whether any ISA row sets it",
    "dateIdentified":   "when a specimen was identified, not when it was collected",
    "identificationVerificationStatus": "nieustalone what values ISA uses",
    # Event detail finer than the station aggregate
    "eventTime":     "station rows span dates, not times",
    "month":         "eventDate already carries it",
    "day":           "eventDate already carries it",
    "habitat":       "free text; nieustalone how consistently ISA fills it",
    "eventRemarks":  "free text, per record",
    # Position detail
    "verbatimDepth":            "decimal min/max depth kept instead",
    "verbatimCoordinateSystem": "we keep the decimal coordinates DwC requires",
    "verbatimSRS":              "we keep the decimal coordinates DwC requires",
    # Record-level boilerplate, constant per archive and already taken from
    # eml.xml where we DO keep it.
    "type":                  "constant 'Event'/'PhysicalObject' per archive",
    "license":               "taken from eml.xml for the archive as a whole",
    "rightsHolder":          "taken from eml.xml",
    "accessRights":          "taken from eml.xml",
    "bibliographicCitation": "taken from eml.xml",
    "institutionID":         "taken from eml.xml",
    "basisOfRecord":         "constant per archive",
    # Other
    "catalogNumber":        "museum accession, per specimen",
    "associatedSequences":  "genetic accessions; no sequence view exists",
    "occurrenceRemarks":    "free text, per record",
    "sex":                  "per specimen; not aggregated",
}


# The occurrence.txt header as ISA publishes it, read from the real archives
# on 2026-09-15. Held as data so the split between "kept" and "refused with a
# reason" can be checked without the network, and so a column the publisher
# ADDS shows up as a diff rather than as silence.
OCC_COLUMNS_SEEN = (
    "id", "dataset_id", "occurrenceID", "catalogNumber", "individualCount",
    "organismQuantity", "organismQuantityType", "occurrenceStatus",
    "associatedSequences", "occurrenceRemarks", "sex", "eventID", "eventDate",
    "eventTime", "year", "month", "day", "habitat", "samplingProtocol",
    "eventRemarks", "locationID", "minimumDepthInMeters",
    "maximumDepthInMeters", "verbatimDepth", "decimalLatitude",
    "decimalLongitude", "verbatimCoordinateSystem", "verbatimSRS",
    "coordinateUncertaintyInMeters", "identificationID", "typeStatus",
    "dateIdentified", "identificationVerificationStatus", "type", "license",
    "rightsHolder", "accessRights", "bibliographicCitation", "institutionID",
    "basisOfRecord", "taxonID", "scientificName", "scientificNameID",
    "kingdom", "phylum", "class", "order", "family", "genus", "taxonRank",
    "taxonomicStatus", "taxonRemarks",
)

_EMOF_NAME = "extendedmeasurementorfact.txt"


def _read_measurements(zf, names: set[str], slug: str) -> tuple[int, list[str]]:
    """`(row_count, sorted distinct measurementType)` from the archive's
    extended-measurement file.

    ⛔ Returns (0, []) for a file that is present but holds only a header —
    which is 98 of the 140 archives — and the SAME (0, []) is never reached
    for a file that fails to parse: that raises. "This archive measured
    nothing" and "we could not read what it measured" are different facts.
    """
    if _EMOF_NAME not in names:
        log.info("deepdata_dwc %s: no %s in the archive", slug, _EMOF_NAME)
        return 0, []
    text = zf.read(_EMOF_NAME).decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    header = set(reader.fieldnames or ())
    if "measurementType" not in header:
        raise ValueError(
            f"{slug}: {_EMOF_NAME} has no measurementType column — header is "
            f"{sorted(header)}. Counting its rows without knowing what they "
            f"measure would be a number that means nothing."
        )
    count = 0
    types: set[str] = set()
    for row in reader:
        count += 1
        t = (row.get("measurementType") or "").strip()
        if t:
            types.add(t)
    return count, sorted(types)


class MissingOccurrenceColumns(ValueError):
    """An archive stopped publishing a column the station build depends on."""


def _iter_occurrences(occ_bytes: bytes, slug: str = "?") -> Iterable[dict[str, Any]]:
    """Stream-parse occurrence.txt; yield only the fields we keep.

    ⛔ Checks the header before reading a single row. A renamed or dropped
    column otherwise costs nothing at parse time and everything afterwards:
    every value comes back None, the station build skips the occurrence for
    want of coordinates, and the archive lands as a clean zero.
    """
    text = occ_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    header = set(reader.fieldnames or ())
    missing = sorted(_OCC_FIELDS_REQUIRED - header)
    if missing:
        raise MissingOccurrenceColumns(
            f"{slug}: occurrence.txt does not publish {missing}. Every station "
            f"built from it would be dropped for want of these values, and the "
            f"archive would parse to zero rows without an error. Header has "
            f"{len(header)} column(s)."
        )
    # ⚠️ Optional columns stay optional on purpose — archives legitimately vary
    # — but a column that vanishes EVERYWHERE is worth knowing about, so log it
    # once per archive rather than per row.
    absent_optional = sorted(set(_OCC_FIELDS) - _OCC_FIELDS_REQUIRED - header)
    if absent_optional:
        log.info("deepdata_dwc %s: occurrence.txt omits optional %s", slug, absent_optional)
    for row in reader:
        yield {k: row.get(k) for k in _OCC_FIELDS}


# ───────────────────────── Station aggregation ─────────────────────────

# eventID examples observed across contractors:
#   NORI:  NORI_D_C5D_5D_MC_117_MC_117.CR_01.ECK.foram_tot.L_040_050_22317
#   TOML:  TOML_<area>_<gear>_<station>.<replicate>...
#   UKSRL: AB02_MC_<station>_<...>
# Strategy: prefer locationID (when contractor provides it), else strip the
# eventID at the first known gear+number marker, else use the full eventID.

_STATION_KEY_RE = re.compile(
    r"^(.+?_(?:MC|BC|EBS|CTD|MUC|VG|GR|MEG)_\d+)",
    re.IGNORECASE,
)
_HORIZON_RE = re.compile(r"L_?(\d{2,4})_(\d{2,4})", re.IGNORECASE)


def _station_key(occ: dict[str, Any]) -> str:
    loc = (occ.get("locationID") or "").strip()
    if loc:
        return loc
    eid = (occ.get("eventID") or "").strip()
    if not eid:
        return f"unknown_{(occ.get('id') or '')[:8]}"
    m = _STATION_KEY_RE.match(eid)
    if m:
        return m.group(1)
    return eid


def _station_id(archive_slug: str, key: str) -> str:
    """Stable hash. Tier 2 uses `archive_slug` as the per-dataset namespace
    (DwC archives use the slug — not a UUID — as `dataset_id`)."""
    return hashlib.sha1(f"{archive_slug}:{key}".encode()).hexdigest()[:16]


def _parse_horizon(event_id: str | None) -> str | None:
    """NORI/TOML scheme: L_<min*10>_<max*10> tenths-of-cm, e.g. L_040_050 → '4-5cm'."""
    if not event_id:
        return None
    m = _HORIZON_RE.search(event_id)
    if not m:
        return None
    a, b = int(m.group(1)) / 10, int(m.group(2)) / 10
    return f"{a:g}-{b:g}cm"


def _safe_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_dt(v: Any) -> datetime | None:
    if not v or not isinstance(v, str):
        return None
    s = v.strip().replace("Z", "+00:00")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def aggregate_stations(
    slug: str,
    archive_meta: dict[str, Any],
    occurrences: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group occurrences by station_key and roll up the metrics.

    Skips occurrences with missing coordinates or dataset_id.
    """
    contractor = parse_contractor_code(archive_meta.get("title") or slug)

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for occ in occurrences:
        if not (occ.get("decimalLatitude") and occ.get("decimalLongitude")):
            continue
        key = _station_key(occ)
        groups[key].append(occ)

    stations: list[dict[str, Any]] = []
    for key, members in groups.items():
        # archive_slug carries the dataset lineage; we hash it with the
        # station_key for a stable station_id.
        lats = [float(m["decimalLatitude"]) for m in members
                if _safe_float(m.get("decimalLatitude")) is not None]
        lons = [float(m["decimalLongitude"]) for m in members
                if _safe_float(m.get("decimalLongitude")) is not None]
        if not lats or not lons:
            continue

        depths_min = [d for d in (_safe_float(m.get("minimumDepthInMeters")) for m in members) if d is not None]
        depths_max = [d for d in (_safe_float(m.get("maximumDepthInMeters")) for m in members) if d is not None]
        coord_unc  = [d for d in (_safe_float(m.get("coordinateUncertaintyInMeters")) for m in members) if d is not None]
        dates      = [d for d in (_safe_dt(m.get("eventDate")) for m in members) if d is not None]
        species    = {m.get("scientificName") for m in members if m.get("scientificName")}
        horizons   = sorted({h for h in (_parse_horizon(m.get("eventID")) for m in members) if h})
        # Most-frequent taxa for the panel. Format "Name (N)" so the UI can
        # render counts without computing them client-side.
        species_counter = Counter(
            m["scientificName"] for m in members if m.get("scientificName")
        )
        phylum_counter = Counter(
            m["phylum"] for m in members if m.get("phylum")
        )
        top_species = [f"{name} ({n})" for name, n in species_counter.most_common(10)]
        top_phyla   = [f"{name} ({n})" for name, n in phylum_counter.most_common(8)]

        # Pick the first non-empty samplingProtocol + locationID we see.
        sp = next((m.get("samplingProtocol") for m in members if m.get("samplingProtocol")), None)
        loc = next((m.get("locationID") for m in members if m.get("locationID")), None)

        stations.append({
            "station_id":          _station_id(slug, key),
            "archive_slug":        slug,
            "contractor_code":     contractor,
            "event_id_raw":        members[0].get("eventID"),
            "location_id":         loc,
            "sampling_protocol":   sp,
            "lat":                 sum(lats) / len(lats),
            "lon":                 sum(lons) / len(lons),
            "depth_m_min":         min(depths_min) if depths_min else None,
            "depth_m_max":         max(depths_max) if depths_max else None,
            "coord_uncertainty_m": max(coord_unc) if coord_unc else None,
            "first_event_date":    min(dates) if dates else None,
            "last_event_date":     max(dates) if dates else None,
            "occurrence_count":    len(members),
            "species_count":       len(species) or None,
            "top_species":         top_species or None,
            "top_phyla":           top_phyla or None,
            "sediment_horizons":   horizons or None,
        })
    return stations


# ───────────────────────── HEAD batch helper ───────────────────────────

async def head_probe_all(
    client: httpx.AsyncClient,
    slugs: Iterable[str],
) -> list[dict[str, Any]]:
    """HEAD-probe many slugs in parallel, bounded by HEAD_CONCURRENCY."""
    sem = asyncio.Semaphore(HEAD_CONCURRENCY)

    async def _one(slug: str) -> dict[str, Any]:
        async with sem:
            return await head_probe(client, slug)

    return await asyncio.gather(*(_one(s) for s in slugs))
