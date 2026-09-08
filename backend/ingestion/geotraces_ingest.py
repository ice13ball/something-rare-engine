# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""GEOTRACES IDP2025 seawater-discrete ingest (dissolved Mn/Fe/Co/Ni/Cu).

Schema verified 2026-06-23 against the real BODC IDP2025 CSV — see
backend/tests/fixtures/geotraces/SCHEMA_NOTES.md. CC-BY 4.0.
"""
from __future__ import annotations
import asyncio, csv, hashlib, io, os, re, subprocess, zipfile, logging
from datetime import datetime, timezone

log = logging.getLogger("geotraces")

IDP2025_ZIP_URL = (
    "https://www.bodc.ac.uk/data/published_data_library/catalogue/"
    "10.5285/123/RN-20251119092622_42C921488D038BE6E0637086ABC09F0C.zip"
)
SEAWATER_MEMBER = "seawater/ascii/GEOTRACES_IDP2025_Seawater.zip"
CSV_MEMBER = "GEOTRACES_IDP2025_Seawater.csv"

TARGET_METALS = ["mn", "fe", "co", "ni", "cu"]
_METAL_COL = {
    "mn": "Mn_D_CONC", "fe": "Fe_D_CONC", "co": "Co_D_CONC",
    "ni": "Ni_D_CONC", "cu": "Cu_D_CONC",
}
# SeaDataNet flags to DROP (bad / missing). Everything else kept with raw flag.
_DROP_FLAGS = {4, 9}

_META_NAMES = {
    "cruise": "Cruise",
    "station": "Station",
    "type": "Type",
    "time": "yyyy-mm-ddThh:mm:ss.sss",
    "lon": "Longitude",
    "lat": "Latitude",
    "bottom_depth": "Bot. Depth",
    "depth": "DEPTH",
}

# Non-measurement columns (cruise/station/bottle metadata). Base names as they
# come out of _base_name() (unit bracket and ":METAVAR:"/":TYPE" suffix stripped).
# Verified against the real IDP2025 header, backend/tests/fixtures/geotraces/
# seawater_real_subset.csv and /tmp/gt_columns.txt on the VPS (2026-09-08).
_META_BASE_NAMES = {
    "Cruise", "Station", "Type", "yyyy-mm-ddThh", "Longitude", "Latitude",
    "Bot. Depth", "Sampling Devices", "Cast Identifiers", "BODC Event Numbers",
    "Radius of Origin", "Duration", "Operator's Cruise Name", "Ship Name",
    "Cruise Period", "Chief Scientist", "GEOTRACES Scientist", "Cruise Aliases",
    "Cruise Information Link", "BODC Cruise Number", "DEPTH",
    "Rosette Bottle Number", "GEOTRACES Sample ID", "Bottle Flag",
    "Cast Identifier", "Sampling Device", "BODC Bottle Number",
    "BODC Event Number", "Single-Cell ID", "NCBI_Metagenome_BioSample_Accession",
    "NCBI_Single-Cell-Genome_BioProject_Accession",
    "NCBI_16S-18S-rRNA-gene_BioSample_Accession",
    "EMBL_EBI_Metagenome_MGNIFY_Analysis_Accession",
}


def normalize_lon(lon: float) -> float:
    return lon - 360.0 if lon > 180.0 else lon


def station_id_for(cruise: str, station: str) -> str:
    raw = f"{cruise}:{station}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _base_name(col: str) -> str:
    # strip " [unit]" and ":METAVAR:..." suffixes
    return col.split(" [")[0].split(":")[0].strip()


def _unit_of(col: str) -> str | None:
    m = re.search(r"\[([^\]]+)\]", col)
    return m.group(1) if m else None


def parse_header(header: list[str]) -> dict:
    base = [_base_name(c) for c in header]
    meta = {}
    for key, want in _META_NAMES.items():
        for i, b in enumerate(header):
            if key == "time":
                # The time column header is literally "yyyy-mm-ddThh:mm:ss.sss" — it
                # contains colons, so _base_name() would truncate it to "yyyy-mm-ddThh".
                # Match on the unit-stripped name only (no ":METAVAR" suffix exists here).
                unit_stripped = b.split(" [")[0]
                if unit_stripped == want or unit_stripped.startswith("yyyy-mm-dd"):
                    meta[key] = i
                    break
            else:
                # metadata columns: match on base name prefix (Bot. Depth, DEPTH, Longitude...)
                if _base_name(b) == want or _base_name(b).startswith(want):
                    meta[key] = i
                    break
    metals = {}
    for short, exact in _METAL_COL.items():
        for i, b in enumerate(base):
            if b == exact:
                # companions: i+1 STANDARD_DEV, i+2 QV:SEADATANET
                if base[i + 1] != "STANDARD_DEV" or not header[i + 2].startswith("QV:"):
                    raise ValueError(f"unexpected companions for {exact}: {header[i+1]},{header[i+2]}")
                metals[short] = {"value": i, "std": i + 1, "qc": i + 2, "unit": _unit_of(header[i])}
                break
    missing = [k for k in ("cruise", "station", "lon", "lat", "depth") if k not in meta]
    if missing:
        raise ValueError(f"missing metadata columns: {missing}")
    return {"meta": meta, "metals": metals}


def _family_of(param_code: str) -> str:
    """Coarse grouping for geotraces_params.family — cosmetic bucketing only,
    never used for QC or unit logic."""
    c = param_code.upper()
    if c.endswith("_CELL_CONC"):
        return "cellular"
    if "SENSOR" in c:
        return "sensor"
    if c.endswith("_D_CONC") or c.endswith("_TD_CONC") or c.endswith("_T_CONC"):
        return "dissolved"
    return "other"


def parse_all_params(header: list[str]) -> list[dict]:
    """Every value column in the header (386 of them), paired with its
    STANDARD_DEV / QV:SEADATANET companions when present.

    Skips metadata columns (_META_BASE_NAMES, anything carrying ':METAVAR:'),
    and the STANDARD_DEV / QV:SEADATANET columns themselves — those are
    consumed as companions of the value column that precedes them, not
    emitted as params of their own.

    Column layout in the real file is NOT uniform: most value columns are
    followed by STANDARD_DEV then QV:SEADATANET, but some (bottle/sensor
    columns, *_CELL_CONC) go straight to QV:SEADATANET with no STANDARD_DEV.
    We only ever trust what is actually in the next one or two cells — never
    assume the pairing and grab a neighbour that isn't ours.
    """
    n = len(header)
    out = []
    i = 0
    while i < n:
        col = header[i]
        base = _base_name(col)
        if col == "STANDARD_DEV" or col.startswith("QV:") or ":METAVAR:" in col or base in _META_BASE_NAMES:
            i += 1
            continue
        std_idx = None
        qc_idx = None
        if i + 2 < n and header[i + 1] == "STANDARD_DEV" and header[i + 2].startswith("QV:"):
            std_idx, qc_idx = i + 1, i + 2
        elif i + 1 < n and header[i + 1].startswith("QV:"):
            qc_idx = i + 1
        out.append({
            "param_code": base,
            "unit": _unit_of(col),
            "family": _family_of(base),
            "value_idx": i,
            "std_idx": std_idx,
            "qc_idx": qc_idx,
        })
        i += 1
    return out


def _f(v: str):
    v = (v or "").strip()
    if v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _i(v: str):
    v = (v or "").strip()
    if v == "":
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _decade(dt: datetime | None):
    return (dt.year // 10) * 10 if dt else None


def _parse_time(v: str):
    v = (v or "").strip()
    if not v:
        return None
    try:
        return datetime.fromisoformat(v).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# Schema field -> per-row header base name. All optional: a missing column
# just leaves the field None, it never blocks the row.
_EXTRA_META_COLS = {
    "geotraces_sample_id": "GEOTRACES Sample ID",
    "sampling_device": "Sampling Device",
    "cast_identifier": "Cast Identifier",
    "bodc_event_number": "BODC Event Number",
    "bodc_bottle_number": "BODC Bottle Number",
    "rosette_bottle_number": "Rosette Bottle Number",
    "bottle_flag": "Bottle Flag",
    "ship_name": "Ship Name",
    "cruise_period": "Cruise Period",
    "chief_scientist": "Chief Scientist",
    "geotraces_scientist": "GEOTRACES Scientist",
    "operators_cruise_name": "Operator's Cruise Name",
    "cruise_information_link": "Cruise Information Link",
    "bodc_cruise_number": "BODC Cruise Number",
    "ncbi_metagenome_biosample": "NCBI_Metagenome_BioSample_Accession",
    "ncbi_single_cell_genome_bioproject": "NCBI_Single-Cell-Genome_BioProject_Accession",
    "ncbi_rrna_biosample": "NCBI_16S-18S-rRNA-gene_BioSample_Accession",
    "embl_ebi_metagenome_analysis": "EMBL_EBI_Metagenome_MGNIFY_Analysis_Accession",
}
_EXTRA_META_INT = {"bodc_event_number", "bodc_bottle_number", "rosette_bottle_number", "bodc_cruise_number"}


def _extra_meta_idx(header: list[str]) -> dict[str, int]:
    base = [_base_name(c) for c in header]
    out = {}
    for field, want in _EXTRA_META_COLS.items():
        for i, b in enumerate(base):
            if b == want:
                out[field] = i
                break
    return out


def parse_stream_header(header: list[str]):
    """Everything derivable from the header alone: the 5-metal `units` dict
    (unchanged contract) and the full `params_meta` list from parse_all_params."""
    h = parse_header(header)
    units = {f"{short}_d": info["unit"] for short, info in h["metals"].items()}
    return units, parse_all_params(header)


def stream_samples(source, batch_size: int = 5000):
    """Stream (sample_dict, value_rows) pairs off a GEOTRACES seawater CSV,
    in batches, without ever holding the whole file or the whole row list in
    memory. `source` may be a path (str) or an already-open text file/handle.

    value_rows is a list of (param_code, value, stddev, qc_flag) tuples — one
    per non-empty, non-dropped measurement cell in that row, covering all 386
    value columns (not just the 5 wide metal columns).
    """
    close_after = False
    if isinstance(source, str):
        f = open(source, encoding="utf-8", errors="replace")
        close_after = True
    else:
        f = source
    try:
        rd = csv.reader(f)
        header = next(rd)
        h = parse_header(header)
        meta, metals = h["meta"], h["metals"]
        params_meta = parse_all_params(header)
        extra = _extra_meta_idx(header)
        maxidx = max(
            [info["qc"] for info in metals.values()]
            + list(meta.values())
            + [p["value_idx"] for p in params_meta]
        )
        batch: list[tuple[dict, list[tuple]]] = []
        # csv_row is the ordinal of this row in the CSV (0-based, counting every
        # data row csv.reader yields). It MUST be incremented before any
        # `continue` in this loop — including the `len(row) <= maxidx` guard
        # above it conceptually and the lat/lon skip below. load() and
        # load_values_from_csv() both stream this same file in the same order
        # in two separate passes; if the counter only advanced for KEPT rows,
        # the two passes would diverge at the first skipped row and every
        # measurement after it would get attached to the wrong bottle. See
        # DEFECT 1, 2026-09-08 audit.
        csv_row = -1
        for row in rd:
            csv_row += 1
            if len(row) <= maxidx:
                continue
            cruise = row[meta["cruise"]].strip()
            station = row[meta["station"]].strip()
            lat = _f(row[meta["lat"]])
            lon = _f(row[meta["lon"]])
            if lat is None or lon is None:
                continue
            rec = {
                "csv_row": csv_row,
                "station_id": station_id_for(cruise, station),
                "cruise": cruise,
                "station": station,
                "sample_time": _parse_time(row[meta["time"]]) if "time" in meta else None,
                "lat": lat,
                "lon": normalize_lon(lon),
                "depth_m": _f(row[meta["depth"]]),
                "bottom_depth_m": _f(row[meta["bottom_depth"]]) if "bottom_depth" in meta else None,
                "params": {},
            }
            for short, info in metals.items():
                val = _f(row[info["value"]])
                qc = _i(row[info["qc"]])
                std = _f(row[info["std"]])
                if val is not None and (qc is None or qc not in _DROP_FLAGS):
                    rec[f"{short}_d"] = val
                    rec[f"{short}_d_qc"] = qc if qc is not None else 0
                    if std is not None:
                        rec["params"][f"{short}_d_sd"] = std
                else:
                    rec[f"{short}_d"] = None
                    rec[f"{short}_d_qc"] = None
            for field, idx in extra.items():
                if idx >= len(row):
                    rec[field] = None
                    continue
                raw = (row[idx] or "").strip()
                if field in _EXTRA_META_INT:
                    rec[field] = _i(raw) if raw else None
                else:
                    rec[field] = raw or None
            # every bottle with usable coordinates is kept — no metal-presence gate.
            value_rows = []
            for p in params_meta:
                if p["value_idx"] >= len(row):
                    continue
                val = _f(row[p["value_idx"]])
                if val is None:
                    continue
                qc = None
                if p["qc_idx"] is not None and p["qc_idx"] < len(row):
                    qc = _i(row[p["qc_idx"]])
                if qc is not None and qc in _DROP_FLAGS:
                    continue
                std = None
                if p["std_idx"] is not None and p["std_idx"] < len(row):
                    std = _f(row[p["std_idx"]])
                value_rows.append((p["param_code"], val, std, qc))
            batch.append((rec, value_rows))
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch
    finally:
        if close_after:
            f.close()


def build_samples(csv_text: str):
    """Thin wrapper over stream_samples() kept for the existing 5-metal test
    contract and any other in-memory caller. Prefer stream_samples()+load()
    for the real ingest — this materializes everything, which is exactly the
    memory blow-up rule 4 forbids for the 268 MB production file."""
    header = next(csv.reader(io.StringIO(csv_text)))
    units, _params_meta = parse_stream_header(header)
    samples = []
    for batch in stream_samples(io.StringIO(csv_text), batch_size=1_000_000):
        samples.extend(rec for rec, _value_rows in batch)
    return samples, units


def derive_stations(samples: list[dict]) -> list[dict]:
    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)
    for s in samples:
        groups[s["station_id"]].append(s)
    out = []
    for sid, rows in groups.items():
        depths = [r["depth_m"] for r in rows if r["depth_m"] is not None]
        times = [r["sample_time"] for r in rows if r["sample_time"]]
        first = rows[0]
        st = {
            "station_id": sid,
            "cruise": first["cruise"],
            "station": first["station"],
            "sample_time": min(times) if times else None,
            "lat": first["lat"],
            "lon": first["lon"],
            "decade": _decade(min(times)) if times else None,
            "n_samples": len(rows),
            "min_depth_m": min(depths) if depths else None,
            "max_depth_m": max(depths) if depths else None,
            "bottom_depth_m": next((r["bottom_depth_m"] for r in rows if r["bottom_depth_m"] is not None), None),
        }
        for short in TARGET_METALS:
            vals = [r[f"{short}_d"] for r in rows if r.get(f"{short}_d") is not None]
            st[f"has_{short}"] = bool(vals)
            st[f"{short}_max"] = max(vals) if vals else None
        out.append(st)
    return out


async def load(pool, samples: list[dict], stations: list[dict], units: dict[str, str],
                params_meta: list[dict] | None = None) -> int:
    """Bulk-write stations + samples (+ params/values if params_meta is given).

    Anti-truncation guard: a parse that yields FEWER samples than are already
    stored refuses to TRUNCATE and returns 0 without stamping the sync log —
    the caller (sync_geotraces) is responsible for not calling _log_sync when
    this returns 0. The count check happens BEFORE the transaction opens, so
    a short parse never even begins clearing the table.

    The executemany argument tuples (including one json.dumps per sample, for
    ~129k rows) are built off the event loop via asyncio.to_thread — only the
    asyncpg I/O itself runs on the loop (DEFECT 3, 2026-09-08 audit).
    """
    async with pool.acquire() as conn:
        # ⛔ The guard runs BEFORE _build_load_args. Building the tuples costs a
        # json.dumps per sample across ~129k rows; on the refusal path that work
        # is thrown away entirely. Cheap check first, expensive work second.
        existing = await conn.fetchval("SELECT count(*) FROM geotraces_samples") or 0
        if len(samples) < existing:
            log.error(
                "geotraces: parse yielded %d samples against %d already stored — "
                "REFUSING to truncate. Existing data kept.", len(samples), existing)
            return 0
        stations_args, samples_args = await asyncio.to_thread(
            _build_load_args, samples, stations)
        async with conn.transaction():
            await conn.execute(
                "TRUNCATE geotraces_samples, geotraces_stations, geotraces_param_units, "
                "geotraces_params, geotraces_values"
            )
            if units:
                await conn.executemany(
                    "INSERT INTO geotraces_param_units(param, unit) VALUES($1,$2)",
                    [(k, v) for k, v in units.items()],
                )
            if params_meta:
                await conn.executemany(
                    """INSERT INTO geotraces_params(param_code,label,unit,family,n_values)
                       VALUES($1,$2,$3,$4,0) ON CONFLICT (param_code) DO NOTHING""",
                    [(p["param_code"], p["param_code"], p["unit"], p["family"]) for p in params_meta],
                )
            await conn.executemany(
                """INSERT INTO geotraces_stations(
                    station_id,cruise,station,sample_time,lat,lon,decade,n_samples,
                    min_depth_m,max_depth_m,bottom_depth_m,
                    has_mn,has_fe,has_co,has_ni,has_cu,mn_max,fe_max,co_max,ni_max,cu_max,geom)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                          $17,$18,$19,$20,$21, ST_SetSRID(ST_MakePoint($6,$5),4326))""",
                stations_args,
            )
            await conn.executemany(
                """INSERT INTO geotraces_samples(
                    station_id,cruise,station,sample_time,lat,lon,depth_m,bottom_depth_m,
                    mn_d,fe_d,co_d,ni_d,cu_d,mn_d_qc,fe_d_qc,co_d_qc,ni_d_qc,cu_d_qc,params,
                    geotraces_sample_id,sampling_device,cast_identifier,bodc_event_number,
                    bodc_bottle_number,rosette_bottle_number,bottle_flag,ship_name,cruise_period,
                    chief_scientist,geotraces_scientist,operators_cruise_name,
                    cruise_information_link,bodc_cruise_number,ncbi_metagenome_biosample,
                    ncbi_single_cell_genome_bioproject,ncbi_rrna_biosample,
                    embl_ebi_metagenome_analysis,csv_row,geom)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,
                          $20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,$33,$34,$35,$36,
                          $37,
                          ST_SetSRID(ST_MakePoint($6,$5),4326))""",
                samples_args,
            )
    return len(samples)


def _build_load_args(samples: list[dict], stations: list[dict]):
    """Build the executemany() argument tuples for load(). CPU-bound (one
    json.dumps per sample) — always call via asyncio.to_thread, never
    directly on the event loop (DEFECT 3, 2026-09-08 audit)."""
    import json
    stations_args = [
        (s["station_id"], s["cruise"], s["station"], s["sample_time"], s["lat"], s["lon"],
         s["decade"], s["n_samples"], s["min_depth_m"], s["max_depth_m"], s["bottom_depth_m"],
         s["has_mn"], s["has_fe"], s["has_co"], s["has_ni"], s["has_cu"],
         s["mn_max"], s["fe_max"], s["co_max"], s["ni_max"], s["cu_max"]) for s in stations
    ]
    samples_args = [
        (s["station_id"], s["cruise"], s["station"], s["sample_time"], s["lat"], s["lon"],
         s["depth_m"], s["bottom_depth_m"], s["mn_d"], s["fe_d"], s["co_d"], s["ni_d"], s["cu_d"],
         s["mn_d_qc"], s["fe_d_qc"], s["co_d_qc"], s["ni_d_qc"], s["cu_d_qc"],
         json.dumps(s["params"]),
         s.get("geotraces_sample_id"), s.get("sampling_device"), s.get("cast_identifier"),
         s.get("bodc_event_number"), s.get("bodc_bottle_number"), s.get("rosette_bottle_number"),
         s.get("bottle_flag"), s.get("ship_name"), s.get("cruise_period"),
         s.get("chief_scientist"), s.get("geotraces_scientist"), s.get("operators_cruise_name"),
         s.get("cruise_information_link"), s.get("bodc_cruise_number"),
         s.get("ncbi_metagenome_biosample"), s.get("ncbi_single_cell_genome_bioproject"),
         s.get("ncbi_rrna_biosample"), s.get("embl_ebi_metagenome_analysis"),
         s["csv_row"],
         ) for s in samples
    ]
    return stations_args, samples_args


async def load_values_from_csv(pool, csv_path: str, params_meta: list[dict],
                                batch_size: int = 5000) -> int:
    """Second pass over the extracted CSV: stream every value cell into
    geotraces_values via copy_records_to_table (~1.25M rows — executemany
    would be far too slow) and update geotraces_params.n_values.

    Keyed on `csv_row` — the ordinal of the row in the CSV, assigned in
    stream_samples() — NOT on "GEOTRACES Sample ID". That column is empty on
    41% of rows (53,092 / 129,148) and, even where present, only 29,944 of
    76,056 values are distinct (46,112 duplicates), which both silently drops
    41% of bottles and violates the (sample_id, param_code) PRIMARY KEY. The
    ordinal is the only guaranteed-unique bottle identifier in this file (see
    DEFECT 1, 2026-09-08 audit — every other natural key was measured and
    also collides). Every row gets one; there is no skip path here.

    The whole load runs inside ONE transaction (DEFECT 2 fix): if any batch
    fails partway through, everything already copied in this call is rolled
    back rather than left as a silently partial table. sync_geotraces()'s
    "already populated" guard additionally checks that geotraces_values is
    non-empty, so even a partial state from before this fix (or a future bug
    that bypasses the transaction) does not skip forever.

    Must be called AFTER load() has committed the corresponding samples (and
    the anti-truncation guard already decided this parse is safe to publish).
    """
    n_values = 0
    param_counts: dict[str, int] = {}
    gen = stream_samples(csv_path, batch_size=batch_size)
    async with pool.acquire() as conn:
        async with conn.transaction():
            while True:
                batch = await asyncio.to_thread(next, gen, None)
                if batch is None:
                    break
                records = []
                for rec, value_rows in batch:
                    sid = rec["csv_row"]
                    for param_code, val, std, qc in value_rows:
                        records.append((sid, param_code, val, std, qc))
                        param_counts[param_code] = param_counts.get(param_code, 0) + 1
                if records:
                    await conn.copy_records_to_table(
                        "geotraces_values",
                        records=records,
                        columns=["sample_id", "param_code", "value", "stddev", "qc_flag"],
                    )
                    n_values += len(records)
            if param_counts:
                await conn.executemany(
                    "UPDATE geotraces_params SET n_values = $2 WHERE param_code = $1",
                    [(k, v) for k, v in param_counts.items()],
                )
    return n_values


def parse_samples_and_meta(csv_path: str, batch_size: int = 5000):
    """Synchronous, CPU/IO-bound pass 1 over the extracted CSV: every sample
    dict (light — no per-param value_rows kept) plus derived stations, units
    and params_meta. Call this via asyncio.to_thread(), never directly on the
    event loop — see sync_geotraces()."""
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        header = next(csv.reader(f))
    units, params_meta = parse_stream_header(header)
    samples: list[dict] = []
    for batch in stream_samples(csv_path, batch_size=batch_size):
        samples.extend(rec for rec, _value_rows in batch)
    stations = derive_stations(samples)
    return samples, stations, units, params_meta


def fetch_and_extract(dest_dir: str) -> str:
    """Download the IDP2025 ZIP via curl -4, extract the seawater CSV, return its path."""
    os.makedirs(dest_dir, exist_ok=True)
    zip_path = os.path.join(dest_dir, "idp2025.zip")
    subprocess.run(
        ["/usr/bin/curl", "-4", "-sS", "-L", "-o", zip_path, IDP2025_ZIP_URL],
        check=True, timeout=1800,
    )
    with zipfile.ZipFile(zip_path) as z:
        inner = z.read(SEAWATER_MEMBER)
    inner_path = os.path.join(dest_dir, "seawater_inner.zip")
    with open(inner_path, "wb") as f:
        f.write(inner)
    with zipfile.ZipFile(inner_path) as z:
        csv_path = os.path.join(dest_dir, CSV_MEMBER)
        with z.open(CSV_MEMBER) as src, open(csv_path, "wb") as dst:
            while chunk := src.read(8 << 20):
                dst.write(chunk)
    return csv_path
