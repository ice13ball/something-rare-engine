# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations
import datetime
import numpy as np

_EPOCH = datetime.date(1770, 1, 1)   # WOD time = days since 1770-01-01


def _clean(v) -> "str | None":
    if v is None:
        return None
    try:
        s = v.decode() if isinstance(v, (bytes, bytearray)) else str(v)
    except Exception:
        return None
    s = s.strip()
    return s or None


def build_oxygen_rows(*, wod_cast_id, lat, lon, time_days, country, z, z_row_size,
                      oxygen, oxygen_flag, oxygen_row_size, oxygen_units, dataset,
                      min_lat=50.0) -> list[dict]:
    """Pure ragged-array → row dicts. All array args are 1-D numpy-like.

    WOD stores ONE INDEPENDENT ragged array per variable: `z` lives on dim `z_obs`,
    `Oxygen` on dim `Oxygen_obs`. Each has its own `<Var>_row_size`. Casts that
    measured no oxygen have `oxygen_row_size == 0` while `z_row_size > 0`, so the
    two cumulative offsets diverge. `oxygen` MUST be sliced with its own offsets.
    """
    zrs = np.nan_to_num(np.asarray(z_row_size)).astype("int64")
    ors = np.nan_to_num(np.asarray(oxygen_row_size)).astype("int64")
    zcum = np.concatenate([[0], np.cumsum(zrs)])
    ocum = np.concatenate([[0], np.cumsum(ors)])
    units = _clean(oxygen_units) or "umol/kg"
    rows: list[dict] = []
    for i in range(len(zrs)):
        if not (float(lat[i]) >= min_lat):
            continue
        if ors[i] == 0:                            # cast measured no oxygen
            continue
        if ors[i] != zrs[i]:
            # WOD reports oxygen at the z levels; a mismatch means the file
            # violates that contract. Drop the cast rather than zip-truncating
            # it into a plausible-looking but wrong profile.
            continue
        t = time_days[i]
        # WOD fill is 0, but fractional values (0 < t < 1) also decode to the epoch
        # day 1770-01-01. Real OSD casts begin in 1900, so anything inside the epoch
        # day is a fill artefact, never a measurement.
        if not np.isfinite(t) or float(t) < 1.0:
            continue
        a, b = int(zcum[i]), int(zcum[i + 1])      # depth offsets
        p, q = int(ocum[i]), int(ocum[i + 1])      # oxygen offsets (independent!)
        levels, flags = [], []
        for d, o, fl in zip(z[a:b], oxygen[p:q], oxygen_flag[p:q]):
            if not np.isfinite(o) or not np.isfinite(d) or float(d) < 0:
                continue
            levels.append([round(float(d), 2), round(float(o), 3)])
            flags.append(int(fl) if np.isfinite(fl) else 0)
        if not levels:
            continue
        levels.sort(key=lambda p: p[0])
        date = _EPOCH + datetime.timedelta(days=float(t))
        worst = max(flags) if flags else 0
        rows.append({
            "wod_cast_id": str(int(wod_cast_id[i])),
            "lat": float(lat[i]), "lon": float(lon[i]),
            "profile_date": date, "decade": (date.year // 10) * 10,
            "cruise": None, "dataset": dataset,
            "country": _clean(country[i]) if country is not None else None,
            "probe_type": None,
            "max_depth_m": levels[-1][0], "n_levels": len(levels),
            "o2_profile": levels, "o2_units": units,
            "qc_flag": worst, "qc_note": (f"WOD QC flag {worst} on some levels") if worst > 0 else None,
        })
    return rows


def parse_wod_oxygen_dataset(src, min_lat: float = 50.0, dataset: str = "OSD") -> list[dict]:
    """Thin xarray wrapper: open a WOD dataset+year netCDF and build rows.
    Lazily imports xarray (not installed locally; verified on the VPS)."""
    import xarray as xr  # lazy
    ds = src if isinstance(src, xr.Dataset) else xr.open_dataset(src, decode_times=False)
    try:
        if "Oxygen" not in ds.variables or "Oxygen_row_size" not in ds.variables:
            return []
        return build_oxygen_rows(
            wod_cast_id=ds["wod_unique_cast"].values,
            lat=ds["lat"].values, lon=ds["lon"].values,
            time_days=ds["time"].values,
            country=ds["country"].values if "country" in ds.variables else None,
            z=ds["z"].values, z_row_size=ds["z_row_size"].values,
            oxygen=ds["Oxygen"].values,
            oxygen_flag=ds["Oxygen_WODflag"].values if "Oxygen_WODflag" in ds.variables
                        else np.zeros(ds["Oxygen"].size),
            oxygen_row_size=ds["Oxygen_row_size"].values,
            oxygen_units=ds["Oxygen"].attrs.get("units", "umol/kg"),
            dataset=dataset, min_lat=min_lat,
        )
    finally:
        if not isinstance(src, xr.Dataset):
            ds.close()


# ---------------------------------------------------------------------------
# Downloader + streaming orchestrator (Task 3)
# ---------------------------------------------------------------------------
import logging, os, pathlib, shutil, subprocess
log = logging.getLogger("wod_oxygen")
_CURL = shutil.which("curl") or "/usr/bin/curl"
CACHE_DIR = pathlib.Path(os.getenv("WOD_CACHE_DIR", "/var/cache/wod-oxygen"))
WOD_BASE = "https://www.ncei.noaa.gov/data/oceans/ncei/wod"
WOD_DATASET = "osd"          # Ocean Station Data (bottle/Winkler) — deepest O2 history
YEAR_START = 1900
# YEAR_END is resolved at call time = current UTC year


def _download_year(dataset: str, year: int) -> "pathlib.Path | None":
    """curl-4 one WOD dataset+year netCDF to the cache. None on 404/failure."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    url = f"{WOD_BASE}/{year}/wod_{dataset}_{year}.nc"
    dest = CACHE_DIR / f"wod_{dataset}_{year}.nc"
    tmp = dest.with_suffix(".nc.tmp")
    try:
        subprocess.run([_CURL, "-4", "-fsSL", "--connect-timeout", "30",
                        "--max-time", "2400", "-o", str(tmp), url], check=True)
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise RuntimeError("empty")
        os.replace(tmp, dest)
        return dest
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        log.info("wod: no/failed file for %s %s (%s)", dataset, year, exc)
        return None


async def _year_present(pool, year: int) -> bool:
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            "SELECT 1 FROM wod_oxygen_profiles WHERE EXTRACT(YEAR FROM profile_date) = $1 LIMIT 1",
            year))


async def _upsert_rows(pool, rows: list[dict]) -> int:
    import json
    n = 0
    async with pool.acquire() as conn:
        for r in rows:
            try:
                await conn.execute("""
                    INSERT INTO wod_oxygen_profiles
                      (wod_cast_id, lat, lon, geom, profile_date, decade, cruise, dataset,
                       country, probe_type, max_depth_m, n_levels, o2_profile, o2_units, qc_flag, qc_note)
                    VALUES ($1,$2,$3, ST_SetSRID(ST_MakePoint($3,$2),4326), $4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13,$14,$15)
                    ON CONFLICT (wod_cast_id) DO UPDATE SET
                      o2_profile = EXCLUDED.o2_profile, n_levels = EXCLUDED.n_levels,
                      max_depth_m = EXCLUDED.max_depth_m, qc_flag = EXCLUDED.qc_flag,
                      qc_note = EXCLUDED.qc_note
                """, r["wod_cast_id"], r["lat"], r["lon"], r["profile_date"], r["decade"],
                     r["cruise"], r["dataset"].upper(), r["country"], r["probe_type"],
                     r["max_depth_m"], r["n_levels"], json.dumps(r["o2_profile"]),
                     r["o2_units"], r["qc_flag"], r["qc_note"])
                n += 1
            except Exception as exc:
                log.warning("wod: skip cast %s: %s", r.get("wod_cast_id"), exc)
    return n


async def sync_wod_oxygen(pool, *, min_lat: float = 50.0, year_start: int = YEAR_START,
                          year_end: "int | None" = None, dataset: str = WOD_DATASET,
                          force: bool = False) -> tuple[int, int]:
    """Stream WOD year files for `dataset`, Arctic-filter, upsert, delete each file.
    Resumable: skips a year already represented in the table unless force=True.
    Returns (casts_parsed, rows_upserted)."""
    import datetime, asyncio
    if year_end is None:
        year_end = datetime.datetime.utcnow().year
    total_parsed = total_ins = 0
    for year in range(year_start, year_end + 1):
        if not force and await _year_present(pool, year):
            continue
        path = await asyncio.to_thread(_download_year, dataset, year)
        if path is None:
            continue
        try:
            rows = await asyncio.to_thread(parse_wod_oxygen_dataset, str(path), min_lat, dataset.upper())
            total_parsed += len(rows)
            total_ins += await _upsert_rows(pool, rows)
        finally:
            try: path.unlink(missing_ok=True)   # keep peak disk = one file
            except Exception: pass
        log.info("wod: year %s -> %d oxygen casts (min_lat=%s, cumulative ins=%d)",
                 year, len(rows), min_lat, total_ins)
    return (total_parsed, total_ins)
