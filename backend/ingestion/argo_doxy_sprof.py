# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Read one Argo GDAC <WMO>_Sprof.nc into the raw per-profile dicts argo_doxy_rules.build_profile takes.

Arrays are read one profile at a time (`ds[var][i]`), never the whole (N_PROF, N_LEVELS) block: the largest
Sprof measured (coriolis/3902120) is 96 MB with N_LEVELS 3296. `open_sprof` goes one step further and YIELDS the
profiles lazily, so a float's full-length lists never coexist: the loader builds the (thinned) stored row of one
profile before the next is read. `read_sprof` is the list-returning wrapper for tests and small callers.
⛔ Never imported by the API process."""
from __future__ import annotations

import contextlib
import pathlib
from collections.abc import Container, Iterator
from datetime import datetime

import netCDF4

from ingestion.argo_doxy_rules import FILL, parse_gdac_time

REQUIRED_VARS = ("CYCLE_NUMBER", "DIRECTION", "JULD", "JULD_QC", "LATITUDE", "LONGITUDE", "POSITION_QC",
                 "STATION_PARAMETERS", "PARAMETER_DATA_MODE", "PRES", "DOXY", "DOXY_QC")


class SprofSchemaError(ValueError):
    """The file lacks a variable the rules need: a float failure, never a crash and never a guess."""


def _chars(a) -> str:
    return a.tobytes().decode("ascii", "replace")


@contextlib.contextmanager
def open_sprof(path: "str | pathlib.Path", want: "Container[tuple[int, bool]] | None" = None):
    """Context manager -> (DATE_UPDATE of the file or None, iterator of raw profile dicts).

    `want` is a container of (cycle, descending): profiles outside it are skipped before any level array is
    read (cheap), and every profile inside it is yielded, a duplicate (cycle, direction) included — what to do
    with a duplicate is the caller's rule. The iterator is only valid inside the `with` (the file is open)."""
    with netCDF4.Dataset(str(path)) as ds:
        ds.set_auto_mask(False)
        missing = [v for v in REQUIRED_VARS if v not in ds.variables]
        if missing:
            raise SprofSchemaError(f"missing variables {missing}")
        upd = parse_gdac_time(_chars(ds["DATE_UPDATE"][:])) if "DATE_UPDATE" in ds.variables else None
        yield upd, _profiles(ds, want)


def _profiles(ds, want) -> Iterator[dict]:
    n = len(ds.dimensions["N_PROF"])
    cyc = ds["CYCLE_NUMBER"][:]
    dirn = _chars(ds["DIRECTION"][:])
    jq, pq = _chars(ds["JULD_QC"][:]), _chars(ds["POSITION_QC"][:])
    juld, lat, lon = ds["JULD"][:], ds["LATITUDE"][:], ds["LONGITUDE"][:]
    sp, pdm = ds["STATION_PARAMETERS"][:], ds["PARAMETER_DATA_MODE"][:]
    has_adj = "DOXY_ADJUSTED" in ds.variables and "DOXY_ADJUSTED_QC" in ds.variables
    has_padj = "PRES_ADJUSTED" in ds.variables
    has_pq, has_paq = "PRES_QC" in ds.variables, "PRES_ADJUSTED_QC" in ds.variables
    for i in range(n):
        if want is not None and (int(cyc[i]), dirn[i] == "D") not in want:
            continue
        names = [_chars(x).strip() for x in sp[i]]
        if "DOXY" not in names:
            continue
        modes = _chars(pdm[i])
        k = names.index("DOXY")
        pres = ds["PRES"][i].tolist()
        nlev = len(pres)
        yield {
            "cycle": int(cyc[i]), "descending": dirn[i] == "D",
            "juld": float(juld[i]), "juld_qc": jq[i], "lat": float(lat[i]), "lon": float(lon[i]),
            "position_qc": pq[i], "doxy_mode": modes[k] if k < len(modes) else " ",
            "pres": pres,
            "pres_adj": ds["PRES_ADJUSTED"][i].tolist() if has_padj else [FILL] * nlev,
            "pres_qc": _chars(ds["PRES_QC"][i]) if has_pq else " " * nlev,
            "pres_adj_qc": _chars(ds["PRES_ADJUSTED_QC"][i]) if has_paq else " " * nlev,
            "doxy": ds["DOXY"][i].tolist(), "doxy_qc": _chars(ds["DOXY_QC"][i]),
            "doxy_adj": ds["DOXY_ADJUSTED"][i].tolist() if has_adj else [FILL] * nlev,
            "doxy_adj_qc": _chars(ds["DOXY_ADJUSTED_QC"][i]) if has_adj else " " * nlev,
        }


def read_sprof(path: "str | pathlib.Path") -> tuple[datetime | None, list[dict]]:
    """The whole float as a list (tests, small files). The loader uses open_sprof, which holds one profile."""
    with open_sprof(path) as (upd, profiles):
        return upd, list(profiles)
