# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Read one WOD23 netCDF (OSD / CTD / PFL year file) into `Cast` records for the `wod-casts` loader.

WOD stores one independent ragged array per variable: `z` on `z_obs`, `Temperature` on `Temperature_obs`, ...
Each variable is sliced by its OWN `<Var>_row_size` cumulative sum, never by z's, and a variable's fill slots are
dropped BEFORE thinning (a float's oxygen sits on the CTD z grid with ~56 % fills between the values). Nothing
here ever zips two ragged arrays: a row-size mismatch drops that variable of that cast and is counted.
Units are checked against `R.EXPECTED_UNITS` and never converted: a change stops the file (`SchemaError`).

File metadata for the loader (flag meanings, instrument, year): `read_file_info(path)` opens the file, checks the
schema and returns a `FileInfo` without reading any cast. The loader calls it first, so a schema problem marks the
file 'error' before anything is staged; `iter_casts` checks the same schema again when it opens the file.

⛔ netCDF4 is imported lazily, inside the functions: the API process never loads this module.
Reject terms written into `stats` (the R11 terms the loader copies to `wod_files.rejects`): `source`,
`no_depth_levels`, `no_values`, `rowsize_mismatch_<code>`, `all_fill_<code>`, `bad_coords`, `no_good`, `no_date`.
Every source cast lands in exactly one of no_depth_levels / no_values / bad_coords / stored; a stored cast with no
good value counts `no_good`, one with a good value but no usable date counts `no_date` (never both, P5)."""
from __future__ import annotations

import logging
import math
import os
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime

import numpy as np

from ingestion import wod_casts_rules as R

log = logging.getLogger(__name__)

META_FIELDS = ("cruise", "orig_cruise", "platform", "vehicle", "wmo_id", "institute", "project", "country",
               "t_instrument", "o2_instrument", "real_time")
_META_VARS = {"cruise": "WOD_cruise_identifier", "orig_cruise": "originators_cruise_identifier",
              "platform": "Platform", "vehicle": "Ocean_Vehicle", "wmo_id": "WMO_ID", "institute": "Institute",
              "project": "Project", "country": "country", "t_instrument": "Temperature_Instrument",
              "o2_instrument": "Oxygen_Instrument", "real_time": "real_time", "dataset": "dataset",
              "access_no": "Access_no"}
FILL_LIMIT = -1e9                          # anything at or below is a fill, whatever the file's _FillValue says
_REQUIRED = ("z", "z_row_size", "z_WODflag", "lat", "lon", "time", "wod_unique_cast")
_FILE_RE = re.compile(r"wod_(osd|ctd|pfl)_([0-9]{4})")


class SchemaError(Exception):
    """The file lacks a variable or flag, or a unit is not the expected one. Stops the file, never converts."""


@dataclass
class FileInfo:
    instrument: str
    year: int
    n_casts: int
    flag_meanings: dict[str, dict[int, str]]       # netCDF variable ("z", "Temperature", ...) -> {flag: meaning}


@dataclass(slots=True)
class Cast:
    cast_id: int
    instrument: str
    dataset: str | None
    lat: float
    lon: float
    cast_date: date | None
    cast_time: datetime | None
    time_precision: str | None
    year: int | None
    meta: dict[str, str | None]
    access_no: int | None
    depth: list[float]
    depth_flag: bytes
    values: dict[str, list[float | None] | None]   # code -> aligned with depth, None = variable absent in this cast
    flags: dict[str, bytes | None]                 # NO_VALUE_FLAG where the variable has no value at that depth
    pflag: list[int | None]                        # per R.VARS; None = the cast has no rows of that variable
    n_src: list[int]                               # per R.VARS; valid (non-fill) source levels before thinning
    n_good: int
    picks: list[int | None]                        # R.N_PICKS scaled smallints
    key: int
    x: float
    y: float


def _int_or_none(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _flag_dict(var) -> dict[int, str]:
    values = getattr(var, "flag_values", None)
    meanings = getattr(var, "flag_meanings", None)
    if values is None or meanings is None:
        return {}
    keys = [int(v) for v in np.atleast_1d(values)]
    words = str(meanings).split()
    if len(keys) != len(words):                                        # an ambiguous pairing is not guessed
        log.warning("flag_values/flag_meanings length mismatch on %s: %d vs %d", getattr(var, "name", "?"),
                    len(keys), len(words))
        return {}
    return dict(zip(keys, words))


def read_info(ds, instrument: str | None = None, year: int | None = None) -> FileInfo:
    """Schema + units check of an open dataset. SchemaError on a missing variable/flag or a unit change."""
    if "casts" not in ds.dimensions:
        raise SchemaError("dimension 'casts' is missing")
    for name in _REQUIRED:
        if name not in ds.variables:
            raise SchemaError(f"variable {name!r} is missing")
    present = [v for v in R.VARS if v[1] in ds.variables]
    if not present:
        raise SchemaError("none of Temperature/Salinity/Oxygen/Phosphate/Silicate/Nitrate is in the file")
    names = ["z"] + [name for _, name, _, _ in present]
    for _, name, _, _ in present:
        for suffix in ("_row_size", "_WODflag", "_WODprofileflag"):
            if name + suffix not in ds.variables:
                raise SchemaError(f"variable {name + suffix!r} is missing")
    for name in names:
        got = getattr(ds.variables[name], "units", None)
        if got != R.EXPECTED_UNITS[name]:
            raise SchemaError(f"{name}: units {got!r}, expected {R.EXPECTED_UNITS[name]!r}")
    meanings = {name: _flag_dict(ds.variables[name + "_WODflag"]) for name in names}
    if instrument is None or year is None:
        try:
            m = _FILE_RE.search(os.path.basename(str(ds.filepath())))
        except (AttributeError, ValueError):               # in-memory or exotic datasets have no path
            m = None
        instrument = instrument if instrument is not None else (m.group(1) if m else "")
        year = year if year is not None else (int(m.group(2)) if m else 0)
    return FileInfo(instrument=instrument, year=year, n_casts=int(ds.dimensions["casts"].size),
                    flag_meanings=meanings)


def read_file_info(path, instrument: str | None = None) -> FileInfo:
    """Open the file, check the schema, return its FileInfo (no cast is read). Raises SchemaError."""
    import netCDF4
    with netCDF4.Dataset(path) as ds:
        return read_info(ds, instrument)


def _column(var, i0: int, i1: int) -> list[str | None]:
    """One per-cast text (or numeric id) variable for casts i0:i1 as stripped text, '' -> None."""
    a = var[i0:i1]
    kind = a.dtype.kind
    out: list[str | None] = []
    if kind == "S" and a.ndim == 2 and a.dtype.itemsize == 1:          # char matrix (casts, strlen)
        rows = np.ascontiguousarray(a).view(f"S{a.shape[1]}").reshape(-1)
        for x in rows:
            out.append(x.decode("utf-8", "replace").strip() or None)
    elif kind in "SUO":
        for x in a.reshape(-1):
            s = x.decode("utf-8", "replace") if isinstance(x, bytes) else str(x)
            out.append(s.split("\x00")[0].strip() or None)
    else:                                                              # integer / float ids (WMO_ID, Access_no)
        fill = getattr(var, "_FillValue", None)
        for x in a.reshape(-1):
            f = float(x)
            if not math.isfinite(f) or f <= FILL_LIMIT or (fill is not None and f == float(fill)):
                out.append(None)
            else:
                out.append(str(int(f)) if f.is_integer() else str(f))
    return out


def _strings(ds, i0: int, i1: int) -> dict[str, list[str | None]]:
    """META_FIELDS + "dataset" + "access_no" (as text) for casts i0:i1; absent variable -> None for every cast."""
    n = i1 - i0
    out: dict[str, list[str | None]] = {}
    for field, name in _META_VARS.items():
        out[field] = _column(ds.variables[name], i0, i1) if name in ds.variables else [None] * n
    return out


def _decode(t, d) -> tuple[date | None, datetime | None, str | None]:
    """R.decode_time that never raises: an absurd `time` (OverflowError) or a NaN `date` (ValueError) is a fill."""
    try:
        tf = float(t)
    except (TypeError, ValueError, OverflowError):
        tf = None
    di = None
    if d is not None:
        try:
            df = float(d)
            di = int(df) if math.isfinite(df) else None
        except (TypeError, ValueError, OverflowError):
            di = None
    try:
        return R.decode_time(tf, di)
    except (OverflowError, ValueError):
        pass
    try:
        return R.decode_time(None, di)                                 # time unusable -> the date decides
    except (OverflowError, ValueError):
        return None, None, None


def iter_casts(path, instrument: str, stats: Counter) -> Iterator[Cast]:
    import netCDF4                                                     # worker-only import
    with netCDF4.Dataset(path) as ds:
        ds.set_auto_mask(False)
        ds.set_auto_chartostring(False)
        read_info(ds, instrument)                                      # raises SchemaError
        n = int(ds.dimensions["casts"].size)
        stats["source"] += n
        zrs = np.clip(np.asarray(ds["z_row_size"][:]).astype(np.int64), 0, None)
        zcum = np.concatenate([[0], np.cumsum(zrs)])
        present = [v for v in R.VARS if v[1] in ds.variables]
        rs = {c: np.clip(np.asarray(ds[f"{name}_row_size"][:]).astype(np.int64), 0, None)
              for c, name, _, _ in present}
        cum = {c: np.concatenate([[0], np.cumsum(a)]) for c, a in rs.items()}   # ⛔ each variable its OWN offsets
        fill = {c: float(getattr(ds[name], "_FillValue", -1e10)) for c, name, _, _ in present}
        pfl = {c: np.asarray(ds[f"{name}_WODprofileflag"][:]) for c, name, _, _ in present}
        cast_ids = np.asarray(ds["wod_unique_cast"][:])
        lat = np.asarray(ds["lat"][:], dtype=np.float64)
        lon = np.asarray(ds["lon"][:], dtype=np.float64)
        tt = np.asarray(ds["time"][:], dtype=np.float64)
        dd = np.asarray(ds["date"][:]) if "date" in ds.variables else None
        coords_ok = np.isfinite(lat) & np.isfinite(lon) & (np.abs(lat) <= 90.0) & (np.abs(lon) <= 180.0)
        i0 = 0
        while i0 < n:
            i1 = int(min(n, max(i0 + 1, np.searchsorted(zcum, zcum[i0] + R.CHUNK_OBS, side="right") - 1)))
            zb, ze = int(zcum[i0]), int(zcum[i1])
            z = np.asarray(ds["z"][zb:ze]).astype(np.float32)
            zf = np.asarray(ds["z_WODflag"][zb:ze]).astype(np.uint8)
            base, vals, flg = {}, {}, {}
            for c, name, _, _ in present:
                a, b = int(cum[c][i0]), int(cum[c][i1])
                base[c] = a
                if b > a:
                    vals[c] = np.asarray(ds[name][a:b])
                    flg[c] = np.asarray(ds[f"{name}_WODflag"][a:b]).astype(np.uint8)
                else:
                    vals[c], flg[c] = np.empty(0, dtype=np.float32), np.empty(0, dtype=np.uint8)
            strings = _strings(ds, i0, i1)
            ok_c = coords_ok[i0:i1]                                    # no Morton key is computed for a bad cast
            x_c, y_c = R.to_3857(np.where(ok_c, lon[i0:i1], 0.0), np.where(ok_c, lat[i0:i1], 0.0))
            key_c = R.morton_key(x_c, y_c)
            for i in range(i0, i1):
                zs, ze_i = int(zcum[i]) - zb, int(zcum[i + 1]) - zb
                per_var = {}
                for c in rs:
                    if rs[c][i] > 0:
                        a, b = int(cum[c][i]) - base[c], int(cum[c][i + 1]) - base[c]
                        per_var[c] = (vals[c][a:b], flg[c][a:b], int(pfl[c][i]), fill[c])
                k = i - i0
                cast = _one_cast(
                    z[zs:ze_i], zf[zs:ze_i], per_var, int(cast_ids[i]), float(lat[i]), float(lon[i]),
                    bool(ok_c[k]), float(x_c[k]), float(y_c[k]), int(key_c[k]), tt[i],
                    None if dd is None else dd[i], {f: col[k] for f, col in strings.items()}, instrument, stats)
                if cast is not None:
                    yield cast
            i0 = i1


def _one_cast(z, zf, per_var, cast_id, lat, lon, coords_ok, x, y, key, t, d, strings, instrument, stats):
    if len(z) == 0:
        stats["no_depth_levels"] += 1
        return None
    z_ok = np.isfinite(z) & (z > FILL_LIMIT)
    valid, good = {}, {}
    for code, (v, f, pf, fill) in per_var.items():
        if len(v) != len(z):                                           # never zip-truncate (rule file)
            stats[f"rowsize_mismatch_{code}"] += 1
            continue
        ok = np.isfinite(v) & (v > FILL_LIMIT) & (v != fill) & z_ok
        if not ok.any():
            stats[f"all_fill_{code}"] += 1
            continue
        valid[code] = ok
        good[code] = ok & (f == R.GOOD_FLAG) & (zf == R.GOOD_FLAG) & (pf == R.GOOD_FLAG)
    if not valid:
        stats["no_values"] += 1
        return None
    if not coords_ok:
        stats["bad_coords"] += 1
        return None
    picks: list[int | None] = [None] * R.N_PICKS
    must: dict[str, set[int]] = {c: set() for c in valid}
    for code in valid:
        var = R.VARS[R.VAR_CODE_TO_INDEX[code]][2]
        for dep, j in enumerate(R.pick_levels(z, good[code])):
            if j is not None:
                picks[R.slot(var, dep)] = R.scaled(float(per_var[code][0][j]), var)
                must[code].add(j)
    if "n" in good and "p" in good:                                    # N* from the same level, both good (R8)
        both = good["n"] & good["p"]
        for dep, j in enumerate(R.pick_levels(z, both)):
            if j is not None:
                ns = float(per_var["n"][0][j]) - R.NSTAR_K * float(per_var["p"][0][j])
                picks[R.slot("nstar", dep)] = R.scaled(ns, "nstar")
                must["n"].add(j)
                must["p"].add(j)
    kept = {}
    for code, ok in valid.items():                                     # drop fills FIRST, then thin
        vj = np.flatnonzero(ok)
        pos = {int(j): k for k, j in enumerate(vj)}
        kept[code] = vj[R.thin_indices(z[vj], {pos[j] for j in must[code]})]
    union = np.array(sorted(set().union(*(set(k.tolist()) for k in kept.values()))), dtype=np.int64)
    where = {int(j): k for k, j in enumerate(union)}
    values: dict[str, list[float | None] | None] = {c: None for c, *_ in R.VARS}
    flags: dict[str, bytes | None] = {c: None for c, *_ in R.VARS}
    for code, ks in kept.items():
        arr: list[float | None] = [None] * len(union)
        fb = bytearray([R.NO_VALUE_FLAG]) * len(union)
        v, f = per_var[code][0], per_var[code][1]
        for j in ks.tolist():
            arr[where[j]] = float(v[j])
            fb[where[j]] = int(f[j])
        values[code], flags[code] = arr, bytes(fb)
    day, ts, prec = _decode(t, d)
    n_good = int(sum(int(g.sum()) for g in good.values()))
    if n_good == 0:
        stats["no_good"] += 1
    elif day is None:
        stats["no_date"] += 1                                          # P5: only a cast with a good value
    return Cast(cast_id=cast_id, instrument=instrument, dataset=strings["dataset"],
                lat=lat, lon=lon, cast_date=day, cast_time=ts, time_precision=prec,
                year=day.year if day else None, meta={k: strings[k] for k in META_FIELDS},
                access_no=_int_or_none(strings["access_no"]),
                depth=[float(x) for x in z[union]], depth_flag=zf[union].tobytes(),
                values=values, flags=flags,
                pflag=[per_var[c][2] if c in per_var else None for c, *_ in R.VARS],
                n_src=[int(valid[c].sum()) if c in valid else 0 for c, *_ in R.VARS],
                n_good=n_good, picks=picks, key=key, x=x, y=y)
