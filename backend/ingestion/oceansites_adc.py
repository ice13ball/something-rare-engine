# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The Davis Strait moorings as a second historical-record source.

North of 60 N the OceanOPS register holds 254 moorings and the OceanSITES GDAC
holds files for 17 of them. 140 of the 254 are the Davis Strait array (names
``DS_C*``, ``DS_WG*``, ``DS_BI*``, one register row per site per year,
2004-2015). Their data is not in the GDAC; it is a CC0 dataset at the NSF Arctic
Data Center::

    doi:10.18739/A2416T169  "Davis Strait hydrographic mooring Level 2 data:
    temperature, salinity, and velocity measurements ... 2004 to 2022"

446 netCDF files, one per sensor per deployment per depth, named
``Davis_<MicroCAT|RCM|ADCP>_[velocity_]<SITE>_<YEAR>_<DEPTH>m_L2.nc``. Discovery is
the DataONE Solr index (``isDocumentedBy:"doi:10.18739/A2416T169"``); the bytes come
from the ADC object endpoint. This module is parsing and matching; the tables are
owned by ``domains/oceansites_history.py``.

⛔ What the real files say (inspected 2026-10-03, fixtures in
``tests/fixtures/oceansites_gdac/adc_davis/``):

* NETCDF4_CLASSIC, CF-1.7, ``time`` in ``Days since 1950-01-01`` (capital D, no
  time of day), ``_FillValue`` ``1e+35`` on every variable, a ``<name>_QC`` flag
  beside each MicroCAT variable and ONE shared ``velocity_QC`` beside the two RCM
  velocities (so the QC variable is found by what it says it grades).
* ⚠️ ``mooring_number`` is a site code (``BI4``) only on the 2007-2014 files. The 2004-2006
  files carry a numeric UW id (``1535``) or ``UW Mooring`` there and ``station`` is
  ``1535`` / ``ooring``; the 2015 files (a different BIO/IOOS layout: ``platform_id``
  ``BI4.30``, ``time_coverage_start`` an epoch number, no ``mooring_number``) have none.
  The site is therefore taken from the ADC's own file name (the one field every file has)
  and CORROBORATED by the file: a site-code attribute (``mooring_number``, ``station``,
  ``platform_id`` before the dot) must not contradict it, and some attribute (those, or the
  ``source`` file name the ADC kept) must name it. See :func:`check_mooring`.
* Variable names ARE the CF standard names. Depth is the variable's
  ``sensor_depth`` attribute (MicroCAT) or the global ``geospatial_vertical_min``
  (RCM); ``sensor_depth_below_sea_surface`` is a time series of a mooring that
  knocks down, not the depth the series is filed under.
* ADCP files (100, 1.4 GB, ``[bin][time]``, bin depth = sensor depth - distance)
  are deliberately not read: no sampling rule for a moving bin axis was decided,
  and the GDAC pipeline treats ADCP bins as "nothing sampleable" for the same
  reason. They are counted, never catalogued.

⛔ Matching is by NAME and DATE, never by position. The register has typos
(DS_BI3 / DS_BI4 2007 carry longitude -66.2 where the site is at -61.2); a
position test would drop exactly the rows whose coordinates are wrong and keep
neighbours. A station links to a file iff the station's mooring name equals the
file's ``mooring_number`` and one of the station's deploy dates lies within
``[time_coverage_start - 3 days, time_coverage_end]``. A file that runs for two
seasons (C4 2013-09-16 .. 2015-09-11) therefore covers both register rows it
spans. Precision over recall: an unlinked station is fine, a wrong link is not.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import httpx

from ingestion import oceansites_history as _gdac
from ingestion import oceansites_opendap as dap

log = logging.getLogger(__name__)

SOURCE = "adc_davis"
DOI = "10.18739/A2416T169"
KEY_PREFIX = "ADC/A2416T169/"
LANDING_URL = f"https://doi.org/{DOI}"

# ⛔ Real text, taken 2026-10-03 from DataCite (api.datacite.org/dois/10.18739/a2416t169)
# and the DOI's own APA rendering (doi.org content negotiation).
CITATION = (
    "Lee, C. (2024). Davis Strait hydrographic mooring Level 2 data: temperature, salinity, "
    "and velocity measurements from the Davis Strait Observing System moorings, 2004 to 2022 "
    "[Dataset]. NSF Arctic Data Center. https://doi.org/10.18739/A2416T169"
)
LICENCE = "CC0 1.0"

SOLR_URL = "https://arcticdata.io/metacat/d1/mn/v2/query/solr/"
OBJECT_URL = "https://arcticdata.io/metacat/d1/mn/v2/object/{identifier}"
SOLR_QUERY = f'isDocumentedBy:"doi:{DOI}" AND -obsoletedBy:*'
SOLR_FIELDS = "id,fileName,formatId,size,checksum,checksumAlgorithm,dateModified"
_PAGE = 500

HTTP_TIMEOUT = 120.0
MAX_BYTES = 60 * 1024 * 1024     # the largest real file is 35 MB (an ADCP, not read)
CONCURRENCY = 3
ABORT_AFTER_UNAVAILABLE = 8      # consecutive "server cannot answer" files end the run
_RETRIES = 2
_RETRY_DELAY = 1.5

# Instruments read for series. ADCP: see the module docstring.
READ_INSTRUMENTS = frozenset({"MicroCAT", "RCM"})
LEAD = timedelta(days=3)         # a station is registered on its deploy date; the file may start a little later

_NAME = re.compile(
    r"^Davis_(?P<inst>[A-Za-z]+)_(?:[a-z]+_)?(?P<mooring>[A-Z]+\d+[A-Za-z]*)_"
    r"(?P<year>\d{4})_(?P<depth>\d+(?:\.\d+)?)m_L2\.nc$"
)


class MooringMismatch(dap.UnsupportedFile):
    """The file name says one mooring and the file itself says another, or nothing in
    the file corroborates the name. A settled "do not link", never a guess."""


class AdcError(Exception):
    """``kind``: ``unavailable`` (5xx, timeout, connection, truncated body: says
    nothing about the file) or ``rejected`` (4xx: the server's settled answer)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


# ─────────────────────────────────────────────────────────────────────────────
# Discovery (Solr)
# ─────────────────────────────────────────────────────────────────────────────

def file_key(file_name: str) -> str:
    """Catalogue key. Namespaced: it can never equal a GDAC path (``DATA/...``)."""
    return KEY_PREFIX + file_name


def change_marker(entry: dict) -> str:
    """What says "the ADC republished this file": its checksum (MD5 in the ADC
    index), else its ``dateModified``."""
    if entry.get("checksum"):
        return f"adc:{entry.get('checksum_algorithm') or 'sum'}:{entry['checksum']}"
    return f"adc:mod:{entry.get('date_modified') or ''}"


def parse_listing(payload: dict) -> list[dict]:
    """One dict per ``.nc`` object of a Solr response. Raises ``ValueError`` on a body
    that is not a Solr response."""
    docs = payload["response"]["docs"]
    out = []
    for d in docs:
        name = d.get("fileName") or ""
        if not name.endswith(".nc") or not d.get("id"):
            continue  # the EML metadata object, resource maps
        m = _NAME.match(name)
        out.append({
            "key": file_key(name),
            "file_name": name,
            "identifier": d["id"],
            "instrument": m["inst"] if m else None,
            "mooring": m["mooring"] if m else None,
            "year": int(m["year"]) if m else None,
            "depth": float(m["depth"]) if m else None,
            "size": d.get("size"),
            "checksum": d.get("checksum"),
            "checksum_algorithm": d.get("checksumAlgorithm"),
            "date_modified": d.get("dateModified"),
        })
    return out


async def fetch_listing(client: httpx.AsyncClient, url: str = SOLR_URL) -> list[dict] | None:
    """Every ``.nc`` object of the dataset, or ``None`` when the ADC could not be asked.

    ⛔ ``None`` is "could not look", never "empty": a 5xx, a timeout, a body that is not
    Solr, a listing that stops short of its own ``numFound`` or holds no netCDF at all
    are all "unusable", and the caller leaves every stored row alone.
    """
    entries: list[dict] = []
    start = 0
    try:
        while True:
            r = await client.get(url, params={
                "q": SOLR_QUERY, "fl": SOLR_FIELDS, "rows": str(_PAGE), "start": str(start),
                "sort": "id asc", "wt": "json",
            }, timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                log.warning("ADC listing: HTTP %s", r.status_code)
                return None
            payload = r.json()
            found = int(payload["response"]["numFound"])
            docs = payload["response"]["docs"]
            entries.extend(parse_listing(payload))
            start += len(docs)
            if not docs or start >= found:
                break
        if start < found:
            log.warning("ADC listing stopped at %d of %d", start, found)
            return None
    except (httpx.TimeoutException, httpx.TransportError, ValueError, KeyError, TypeError) as exc:
        log.warning("ADC listing failed: %s", type(exc).__name__)
        return None
    if not entries:
        log.warning("ADC listing holds no netCDF object — treated as unusable")
        return None
    return entries


def in_scope(entry: dict) -> bool:
    """A file we read: a recognised name and an instrument with a sampling rule."""
    return entry.get("instrument") in READ_INSTRUMENTS and entry.get("mooring") is not None


# ─────────────────────────────────────────────────────────────────────────────
# Download
# ─────────────────────────────────────────────────────────────────────────────

async def download(client: httpx.AsyncClient, entry: dict) -> bytes:
    """The file's bytes. Raises :class:`AdcError`. A body that is not what the index
    says it is (wrong size, wrong MD5) is a truncated transfer: ``unavailable``."""
    if (entry.get("size") or 0) > MAX_BYTES:  # the index already says so: do not even ask
        raise AdcError("rejected", f"{entry['size']} bytes, over the {MAX_BYTES >> 20} MiB cap")
    url = OBJECT_URL.format(identifier=entry["identifier"])
    last: AdcError | None = None
    for attempt in range(_RETRIES):
        try:
            async with client.stream("GET", url, timeout=HTTP_TIMEOUT, follow_redirects=True) as r:
                if r.status_code == 200:
                    declared = int(r.headers.get("content-length") or 0)
                    if declared > MAX_BYTES:
                        raise AdcError("rejected", f"larger than the {MAX_BYTES >> 20} MiB cap")
                    chunks, n = [], 0
                    async for block in r.aiter_bytes(1 << 20):
                        n += len(block)
                        if n > MAX_BYTES:
                            raise AdcError("rejected", f"larger than the {MAX_BYTES >> 20} MiB cap")
                        chunks.append(block)
                    body = b"".join(chunks)
                    if entry.get("size") is not None and len(body) != entry["size"]:
                        last = AdcError("unavailable", f"{len(body)} bytes, index says {entry['size']}")
                    elif (str(entry.get("checksum_algorithm") or "").upper() == "MD5" and entry.get("checksum")
                          and hashlib.md5(body).hexdigest() != entry["checksum"].lower()):
                        last = AdcError("unavailable", "MD5 differs from the index")
                    else:
                        return body
                elif r.status_code >= 500 or r.status_code == 429:
                    last = AdcError("unavailable", f"HTTP {r.status_code}")
                else:
                    raise AdcError("rejected", f"HTTP {r.status_code}")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = AdcError("unavailable", type(exc).__name__)
        if attempt + 1 < _RETRIES:
            await asyncio.sleep(_RETRY_DELAY * (attempt + 1))
    assert last is not None
    raise last


# ─────────────────────────────────────────────────────────────────────────────
# netCDF
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ParsedFile:
    mooring: str
    start: datetime
    end: datetime
    lat: float | None
    lon: float | None
    min_depth: float | None
    max_depth: float | None
    parameters: list[str]
    series: list[dap.SeriesRow] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    fills_nulled: int = 0


def _parse_coverage(value) -> datetime | None:
    """``2010-09-15 13:00:00`` (the files' own form) or ISO ``T``/``Z``."""
    m = re.match(r"^\s*(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?", str(value or ""))
    if not m:
        return None
    y, mo, d, hh, mi, ss = m.groups()
    try:
        return datetime(int(y), int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0), tzinfo=timezone.utc)
    except ValueError:
        return None


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and abs(f) < 1e30 else None


def _flat_list(v) -> list[float]:
    if hasattr(v, "tolist"):
        v = v.tolist()
    if not isinstance(v, (list, tuple)):
        v = [v]
    out = []
    for x in v:
        try:
            out.append(float(x))
        except (TypeError, ValueError):
            pass
    return out


def _variable_attrs(var) -> dict[str, object]:
    out: dict[str, object] = {}
    for a in var.ncattrs():
        v = var.getncattr(a)
        if isinstance(v, bytes):
            v = v.decode("utf-8", "replace")
        out[a] = v if isinstance(v, str) else _flat_list(v)
    return out


def _depth_of(var_attrs: dict, glob: dict, name_depth: float | None = None) -> float | None:
    """The nominal depth a series is filed under: the variable's ``sensor_depth``
    (a string such as ``'96.0'`` on the 2007-2014 MicroCAT variables), else the global
    ``instrument_depth`` (RCM; its ``geospatial_vertical_*`` can differ by metres), else
    the global vertical extent when it is one number, else the depth in the ADC file name
    (the 2015 files carry only a pressure range). Never the time-varying
    ``sensor_depth_below_sea_surface``."""
    sd = var_attrs.get("sensor_depth")
    if isinstance(sd, list) and sd:
        sd = sd[0]
    d = _num(sd)
    if d is not None:
        return d
    d = _num(_first(glob.get("instrument_depth")))
    if d is not None:
        return d
    lo, hi = _num(_first(glob.get("geospatial_vertical_min"))), _num(_first(glob.get("geospatial_vertical_max")))
    if (lo is not None and hi is not None and lo == hi
            and str(glob.get("geospatial_vertical_units") or "").lower().startswith("met")):
        return lo
    return name_depth


def _position(glob: dict, name: str, short: str) -> float | None:
    """``latitude`` / ``longitude`` global attribute, else the geospatial extent when it
    is one number (the 2015 files have only that). Informational: matching never uses it."""
    d = _num(_first(_flat_list(glob.get(name))))
    if d is not None:
        return d
    lo = _num(_first(_flat_list(glob.get(f"geospatial_{short}_min"))))
    hi = _num(_first(_flat_list(glob.get(f"geospatial_{short}_max"))))
    return lo if lo is not None and lo == hi else None


def _first(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


_SITE = re.compile(r"^[A-Za-z]{1,3}\d{1,2}[A-Za-z]?$")


def mooring_claims(glob: dict) -> tuple[set[str], set[str]]:
    """``(strong, weak)``: the site codes a file's attributes name.

    strong: ``mooring_number``, ``station`` and ``platform_id`` (before the dot) when
    they look like a site code (``BI4``, ``WG15``, ``C4``) — ``1535``, ``UW Mooring``
    and ``ooring`` are real values in the 2004-2006 files and say nothing. weak: site-like
    upper-case tokens in the base name of the ``source`` attribute (the file the ADC
    converted from, ``MCTD_KN179-05_BI4_3308_1800.nc``)."""
    strong: set[str] = set()
    for key in ("mooring_number", "station"):
        v = str(glob.get(key) or "").strip()
        if _SITE.match(v):
            strong.add(_norm(v))
    pid = str(glob.get("platform_id") or "").strip().split(".")[0]
    if _SITE.match(pid):
        strong.add(_norm(pid))
    weak = {_norm(t) for t in re.split(r"[^A-Za-z0-9]+", str(glob.get("source") or "").rsplit("/", 1)[-1])
            if t and t == t.upper() and _SITE.match(t)}
    return strong, weak


def check_mooring(expected: str, glob: dict) -> None:
    """Raise :class:`MooringMismatch` unless the file corroborates the mooring in its name."""
    want = _norm(expected)
    strong, weak = mooring_claims(glob)
    if strong and want not in strong:
        raise MooringMismatch(f"file name says {expected!r}, the file's own attributes say {sorted(strong)}")
    if want not in strong | weak:
        raise MooringMismatch(f"nothing in the file names mooring {expected!r}")


def _qc_variable(name: str, std: str, names: dict, vattrs: dict) -> str | None:
    """The flag variable that grades ``name``: ``<name>_QC``; else the one ``*_QC``
    variable that is nobody's own flag and whose ``long_name`` names this standard
    name (the RCM's single ``velocity_QC`` over both velocities). Two candidates is
    no answer: the series is stored without flags rather than with a guess."""
    own = f"{name}_QC"
    if own in names:
        return own
    cands = [q for q in names
             if q.endswith("_QC") and q[:-3] not in names
             and std in str(vattrs[q].get("long_name") or "")]
    return cands[0] if len(cands) == 1 else None


def parse_file(raw: bytes, expect_mooring: str | None = None,
               name_depth: float | None = None) -> ParsedFile:
    """Header and strided series of one Davis netCDF.

    ``expect_mooring`` / ``name_depth`` come from the ADC file name. With a mooring the
    file must corroborate it (:func:`check_mooring`, raises :class:`MooringMismatch`);
    without one the file's own site-code attribute is used.

    Raises :class:`dap.UnsupportedFile` when it is not a file we can place (no site, no
    coverage) — the caller records that as a settled "nothing to read", not as an outage.
    """
    import netCDF4  # late: the module imports cleanly where the C library is absent

    try:
        ds = netCDF4.Dataset("davis.nc", mode="r", memory=raw)
    except Exception as exc:
        raise dap.UnsupportedFile(f"not a readable netCDF ({type(exc).__name__})") from exc
    try:
        ds.set_auto_maskandscale(False)  # the file's own _FillValue is applied below, by us
        glob = {a: ds.getncattr(a) for a in ds.ncattrs()}
        if expect_mooring:
            check_mooring(expect_mooring, glob)
            mooring = expect_mooring
        else:
            strong, _weak = mooring_claims(glob)
            if len(strong) != 1:
                raise dap.UnsupportedFile("the file does not name exactly one mooring")
            mooring = next(iter(strong))
        tvar = next((v for k, v in ds.variables.items() if k.lower() == "time"), None)
        if tvar is None or len(tvar.dimensions) != 1:
            raise dap.UnsupportedFile("no TIME variable")
        tattrs = _variable_attrs(tvar)
        origin, unit_s = dap.parse_time_units(
            tattrs.get("units") if isinstance(tattrs.get("units"), str) else None,
            tattrs.get("calendar") if isinstance(tattrs.get("calendar"), str) else None)
        raw_times = [float(x) for x in tvar[:].tolist()]
        times = [dap.decode_time(t, origin, unit_s) for t in raw_times]
        tfills = tuple(_flat_list(tattrs.get("_FillValue", [])) + _flat_list(tattrs.get("missing_value", [])))
        valid = [t for t, rt in zip(times, raw_times) if t is not None and not dap.is_fill(rt, tfills)]
        start = _parse_coverage(glob.get("time_coverage_start")) or (min(valid) if valid else None)
        end = _parse_coverage(glob.get("time_coverage_end")) or (max(valid) if valid else None)
        if start is None or end is None or end < start:
            raise dap.UnsupportedFile("no usable time coverage")
        tname = tvar.name
        n_time = len(raw_times)

        names = ds.variables
        vattrs = {k: _variable_attrs(v) for k, v in names.items()}
        out = ParsedFile(
            mooring=mooring, start=start, end=end,
            lat=_position(glob, "latitude", "lat"),
            lon=_position(glob, "longitude", "lon"),
            min_depth=None, max_depth=None, parameters=[],
        )
        stride = dap.ceil_div(n_time, dap.MAX_SAMPLES)
        depths: list[float] = []
        for name, var in names.items():
            at = vattrs[name]
            std = at.get("standard_name") if isinstance(at.get("standard_name"), str) else None
            if name == tname or name.endswith("_QC") or std not in dap.HISTORY_STANDARD_NAMES:
                continue
            if dap.is_packed(at):
                out.skipped.append((name, dap.PACKED_REASON))
                continue
            if tuple(d.lower() for d in var.dimensions) != (tname.lower(),) or len(var) != n_time:
                out.skipped.append((name, "not a plain [time] series"))
                continue
            out.parameters.append(std)
            fills = tuple(_flat_list(at.get("_FillValue", [])) + _flat_list(at.get("missing_value", [])))
            qname = _qc_variable(name, std, names, vattrs)
            qfills = tuple(_flat_list(vattrs[qname].get("_FillValue", []))) if qname else ()
            vals_all = var[:].tolist()
            qc_all = names[qname][:].tolist() if qname else None
            ts, vs, qs = [], [], []
            for i in range(0, n_time, stride):
                t = times[i]
                if t is None or dap.is_fill(raw_times[i], tfills):
                    continue
                v = vals_all[i]
                if dap.is_fill(v, fills):
                    vs.append(None)
                    out.fills_nulled += 1
                else:
                    vs.append(float(v))
                qs.append(dap._qc_value(qc_all[i], qfills) if qc_all is not None else None)
                ts.append(t)
            good = [t for t, v in zip(ts, vs) if v is not None]
            if not good:
                continue  # a variable with nothing real in the sample: nothing to store
            depth = _depth_of(at, glob, name_depth)
            if depth is not None:
                depths.append(depth)
            out.series.append(dap.SeriesRow(
                variable=name, depth_index=0, depth_m=depth,
                units=at.get("units") if isinstance(at.get("units"), str) else None,
                long_name=at.get("long_name") if isinstance(at.get("long_name"), str) else None,
                standard_name=std, n_total=n_time, stride=stride, times=ts, vals=vs, qc=qs,
                first_time=good[0], last_time=good[-1],
            ))
        if depths:
            out.min_depth, out.max_depth = min(depths), max(depths)
        else:
            d = _depth_of({}, glob, name_depth)
            out.min_depth = out.max_depth = d
        out.parameters = sorted(set(out.parameters))
        return out
    finally:
        ds.close()


# ─────────────────────────────────────────────────────────────────────────────
# Matching
# ─────────────────────────────────────────────────────────────────────────────

_STATION = re.compile(r"^DS[_-]([A-Z0-9._-]+)$")


def _norm(x: str | None) -> str:
    """Upper-case alphanumerics only. Drops the trailing ``\\xa0`` some OceanOPS names carry."""
    return re.sub(r"[^A-Z0-9]", "", (x or "").upper())


def station_mooring(station_name: str | None) -> str | None:
    """``'DS_BI4\\xa0'`` -> ``'BI4'``, ``'DS_C6a'`` -> ``'C6A'``, ``'DS_WG1.5'`` -> ``'WG15'``;
    ``None`` for a name that is not a Davis Strait register name (``DS_`` prefix required:
    a bare ``BI4`` elsewhere is not ours).

    The ``.`` is dropped like every other punctuation: the register's ``WG1.5`` is the
    ADC's ``WG15`` (checked 2026-10-03: nine register rows 2007-2015 within 100 m of the
    fifteen ``WG15`` files, deploy dates within a day of each file's start)."""
    clean = re.sub(r"\s+", "", (station_name or "").upper())  # \s covers \xa0 in a str
    m = _STATION.match(clean)
    return _norm(m.group(1)) if m else None


def _as_utc(d) -> datetime | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    if isinstance(d, date):
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return None


def match_adc_files(stations: list[dict], deployments: list[dict], files: list[dict]) -> list[dict]:
    """Link Davis Strait files to register stations by NAME and DATE.

    ``stations``: ``{ref, name, deploy_date, lat, lon}``. ``deployments``:
    ``{base_ref, name, deploy_date, lat, lon}``. ``files``: ``{file, platform_code
    (the file's mooring_number), start_time, end_time, lat, lon}``.

    A (station, file) pair links iff the station's mooring name (``DS_`` stripped)
    equals the file's mooring AND one of the station's dates (its own deploy date,
    or a deployment of the same base ref) lies in ``[start - 3 days, end]``. The
    position is NOT tested. ``distance_km`` is stored as information only (so a
    register typo is visible, never acted on); ``-1`` when a position is missing.
    """
    by_base: dict[str, list[dict]] = {}
    for d in deployments:
        by_base.setdefault(d["base_ref"], []).append(d)
    by_mooring: dict[str, list[dict]] = {}
    for f in files:
        if f.get("start_time") is None or f.get("end_time") is None:
            continue
        by_mooring.setdefault(_norm(f.get("platform_code")), []).append(f)

    links: dict[tuple[str, str], dict] = {}
    for st in stations:
        pairs = [(st.get("name"), st.get("deploy_date"), st.get("lat"), st.get("lon"))]
        pairs += [(d.get("name") or st.get("name"), d.get("deploy_date"), d.get("lat"), d.get("lon"))
                  for d in by_base.get(st["ref"], [])]
        for name, when, lat, lon in pairs:
            moor = station_mooring(name)
            when_utc = _as_utc(when)
            if not moor or when_utc is None:
                continue
            for f in by_mooring.get(moor, ()):
                # The register holds a DATE, the file a timestamp: compare days, so a
                # deployment registered on the 17th matches a file that starts on the 20th.
                if not ((f["start_time"] - LEAD).date() <= when_utc.date() <= f["end_time"].date()):
                    continue
                dist = -1.0
                if None not in (lat, lon, f.get("lat"), f.get("lon")):
                    dist = round(_gdac.haversine_km(lat, lon, f["lat"], f["lon"]), 2)
                key = (st["ref"], f["file"])
                if key not in links:
                    links[key] = {"station_ref": st["ref"], "file": f["file"],
                                  "rule": "adc-name-date", "distance_km": dist}
    return list(links.values())
