# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""GEOTRACES IDP2025 seawater-discrete ingest (dissolved Mn/Fe/Co/Ni/Cu).

Schema verified 2026-06-23 against the real BODC IDP2025 CSV — see
backend/tests/fixtures/geotraces/SCHEMA_NOTES.md. CC-BY 4.0.
"""
from __future__ import annotations
import csv, hashlib, io, os, re, subprocess, zipfile, logging
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


def build_samples(csv_text: str):
    rd = csv.reader(io.StringIO(csv_text))
    header = next(rd)
    h = parse_header(header)
    meta, metals = h["meta"], h["metals"]
    units = {f"{short}_d": info["unit"] for short, info in metals.items()}
    samples = []
    maxidx = max([info["qc"] for info in metals.values()] + list(meta.values()))
    for row in rd:
        if len(row) <= maxidx:
            continue
        cruise = row[meta["cruise"]].strip()
        station = row[meta["station"]].strip()
        lat = _f(row[meta["lat"]])
        lon = _f(row[meta["lon"]])
        if lat is None or lon is None:
            continue
        rec = {
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
        any_metal = False
        for short, info in metals.items():
            val = _f(row[info["value"]])
            qc = _i(row[info["qc"]])
            std = _f(row[info["std"]])
            if val is not None and (qc is None or qc not in _DROP_FLAGS):
                rec[f"{short}_d"] = val
                rec[f"{short}_d_qc"] = qc if qc is not None else 0
                if std is not None:
                    rec["params"][f"{short}_d_sd"] = std
                any_metal = True
            else:
                rec[f"{short}_d"] = None
                rec[f"{short}_d_qc"] = None
        # keep every sample that has depth + at least one metal value (profile context)
        if any_metal:
            samples.append(rec)
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


async def load(pool, samples: list[dict], stations: list[dict], units: dict[str, str]) -> int:
    import json
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE geotraces_samples, geotraces_stations, geotraces_param_units")
            if units:
                await conn.executemany(
                    "INSERT INTO geotraces_param_units(param, unit) VALUES($1,$2)",
                    [(k, v) for k, v in units.items()],
                )
            await conn.executemany(
                """INSERT INTO geotraces_stations(
                    station_id,cruise,station,sample_time,lat,lon,decade,n_samples,
                    min_depth_m,max_depth_m,bottom_depth_m,
                    has_mn,has_fe,has_co,has_ni,has_cu,mn_max,fe_max,co_max,ni_max,cu_max,geom)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                          $17,$18,$19,$20,$21, ST_SetSRID(ST_MakePoint($6,$5),4326))""",
                [(s["station_id"], s["cruise"], s["station"], s["sample_time"], s["lat"], s["lon"],
                  s["decade"], s["n_samples"], s["min_depth_m"], s["max_depth_m"], s["bottom_depth_m"],
                  s["has_mn"], s["has_fe"], s["has_co"], s["has_ni"], s["has_cu"],
                  s["mn_max"], s["fe_max"], s["co_max"], s["ni_max"], s["cu_max"]) for s in stations],
            )
            await conn.executemany(
                """INSERT INTO geotraces_samples(
                    station_id,cruise,station,sample_time,lat,lon,depth_m,bottom_depth_m,
                    mn_d,fe_d,co_d,ni_d,cu_d,mn_d_qc,fe_d_qc,co_d_qc,ni_d_qc,cu_d_qc,params,geom)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,
                          ST_SetSRID(ST_MakePoint($6,$5),4326))""",
                [(s["station_id"], s["cruise"], s["station"], s["sample_time"], s["lat"], s["lon"],
                  s["depth_m"], s["bottom_depth_m"], s["mn_d"], s["fe_d"], s["co_d"], s["ni_d"], s["cu_d"],
                  s["mn_d_qc"], s["fe_d_qc"], s["co_d_qc"], s["ni_d_qc"], s["cu_d_qc"],
                  json.dumps(s["params"])) for s in samples],
            )
    return len(samples)


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
