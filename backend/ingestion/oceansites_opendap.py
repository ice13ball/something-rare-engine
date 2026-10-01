# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Strided OPeNDAP reads of OceanSITES GDAC files — the historical record.

``ingestion/oceansites_gdac.py`` reads one value per variable (the latest) for
the live observation sync. This module reads the *whole* record of a file, but
only an every-k-th sample of it: ``stride = ceil(N / 150)`` along TIME and up to
10 depth levels per variable. Every stored number is a real measurement taken
by the instrument — **never an average, never converted** (units pass through
exactly as the file declares them).

Per file the requests are: ``.dds`` (shapes), ``.das`` (units, standard names,
fill values, QC variable names, time units) and ONE ``.ascii`` constraint that
carries TIME, every wanted variable, its QC variable and the DEPTH axis.

The three layouts met in the real GDAC (fixtures under
``tests/fixtures/oceansites_gdac/opendap/``):

* ``Grid`` 2-D  ``TEMP[TIME][DEPTH]`` (TAO per-variable files, PAP) — addressed
  ``TEMP.TEMP[...]``;
* ``Grid`` 4-D  ``TEMP[TIME][DEPTH][LATITUDE=1][LONGITUDE=1]`` (MBARI);
* plain array  ``TEMP[TIME]`` with a scalar ``DEPTH[1]`` (LOCO-IRMINGSEA SBE37)
  — addressed ``TEMP[...]``, and ``TEMP.TEMP[...]`` is a 400 there.

The query brackets MUST be percent-encoded (raw ``[`` is a 400 from tomcat).

⛔ A fill value is whatever the variable's own ``_FillValue`` / ``missing_value``
says, plus anything non-finite or of magnitude >= 1e30 (the TAO files carry
``1.0E33`` next to a declared fill of ``-999.0``; it is not a measurement).
No other threshold is applied — 99999 and -999 are only fill when the file says so.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)

OPENDAP_BASE = "https://tds0.ifremer.fr/thredds/dodsC/CORIOLIS-OCEANSITES-GDAC-OBS"

MAX_SAMPLES = 150          # strided samples kept per (file, variable, depth)
MAX_DEPTHS = 10            # depth levels kept per (file, variable)
MAX_FILES_PER_SERIES = 30  # files chosen per (station, standard_name)
HTTP_TIMEOUT = 30.0
_RETRIES = 2               # attempts per request on 5xx / transport errors
_RETRY_DELAY = 1.5         # seconds, doubled on the second retry
REQUEST_DELAY = 0.05       # pause after every request, inside the semaphore

# CF standard names we keep (spec, Design item 3). Matching is by the .das
# ``standard_name`` of the file variable, never by its (inconsistent) short name.
HISTORY_STANDARD_NAMES: frozenset[str] = frozenset({
    "sea_water_temperature",
    "sea_water_practical_salinity",
    "sea_water_salinity",
    "mass_concentration_of_oxygen_in_sea_water",
    "moles_of_oxygen_per_unit_mass_in_sea_water",
    "mole_concentration_of_dissolved_molecular_oxygen_in_sea_water",
    "eastward_sea_water_velocity",
    "northward_sea_water_velocity",
    "sea_surface_temperature",
    "mass_concentration_of_chlorophyll_in_sea_water",
})

# D (delayed, fully QC'd) > M (mixed) > P (provisional) > R (real-time).
_MODE_RANK = {"D": 0, "M": 1, "P": 2, "R": 3}

_EPOCH = datetime(1950, 1, 1, tzinfo=timezone.utc)


# ──────────────────────────── errors ────────────────────────────────────────


class OpendapError(Exception):
    """A request failed. ``kind`` is ``unavailable`` (5xx, timeout, connection:
    the server cannot answer — says nothing about the data) or ``rejected``
    (4xx: this constraint/file is not servable). Neither means "no data"."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class UnsupportedFile(Exception):
    """The file parsed but has no variable we can sample honestly (not an outage).

    ``packed`` names the wanted variables left out because they are stored packed
    (``scale_factor`` / ``add_offset``), so the caller can count them."""

    def __init__(self, message: str, packed: list[str] | None = None):
        super().__init__(message)
        self.packed = packed or []


# Why a packed variable is left out. DAP2 serves the RAW stored integers, so a
# variable with a non-trivial scale_factor / add_offset would be stored unscaled —
# a wrong number that looks right. We leave it out and say so (never guess a scale).
PACKED_REASON = "packed (scale_factor/add_offset) is not supported"


# ──────────────────────────── DDS ───────────────────────────────────────────


@dataclass(frozen=True)
class VarDecl:
    name: str
    grid: bool                          # addressed VAR.VAR[...] when True
    dims: tuple[tuple[str, int], ...]   # (dim name, size) in storage order
    dtype: str = ""


_DECL_RE = re.compile(r"^\s*(\w+)\s+(\w+)((?:\[[^\]]*\])*)\s*;\s*$")
_DIM_RE = re.compile(r"\[\s*(?:(\w+)\s*=\s*)?(\d+)\s*\]")
_CLOSE_RE = re.compile(r"^\s*\}\s*([^;]*);\s*$")


def _dims(text: str) -> tuple[tuple[str, int], ...]:
    return tuple((m.group(1) or "", int(m.group(2))) for m in _DIM_RE.finditer(text))


def parse_dds(text: str) -> dict[str, VarDecl]:
    """``{variable: VarDecl}`` from a .dds (or the header of an .ascii response).

    A ``Grid`` / ``Structure`` block is one variable named by its closing
    ``} NAME;`` and shaped by its first (ARRAY) member.
    """
    out: dict[str, VarDecl] = {}
    stack: list[dict] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s:
            continue
        if s.endswith("{"):
            kind = s[:-1].strip()
            stack.append({"kind": kind, "members": []})
            continue
        m = _CLOSE_RE.match(line)
        if m and stack:
            blk = stack.pop()
            if blk["kind"] in ("Grid", "Structure") and blk["members"] and not stack[1:]:
                decl = blk["members"][0]
                out[m.group(1).strip()] = VarDecl(m.group(1).strip(), blk["kind"] == "Grid",
                                                 decl.dims, decl.dtype)
            continue
        if s in ("ARRAY:", "MAPS:"):
            if stack:
                stack[-1]["section"] = s
            continue
        d = _DECL_RE.match(line)
        if d and stack:
            decl = VarDecl(d.group(2), False, _dims(d.group(3)), d.group(1))
            top = stack[-1]
            if len(stack) == 1:  # direct child of Dataset
                out[decl.name] = decl
            elif top["kind"] == "Grid":
                if top.get("section") != "MAPS":
                    top["members"].append(decl)
            else:
                top["members"].append(decl)
    return out


# ──────────────────────────── DAS ───────────────────────────────────────────

_TOKEN_RE = re.compile(r'"((?:[^"\\]|\\.)*)"|([{};,])|([^\s{};,"]+)', re.S)


def parse_das(text: str) -> dict[str, dict[str, object]]:
    """``{variable: {attribute: str | list[float]}}``; globals under ``NC_GLOBAL``.

    A tokenizer, not a line parser: OceanSITES ``summary`` / ``comment`` strings
    contain ``;``, ``{`` and newlines inside their quotes. Nested containers
    (``DODS { ... }`` inside a string variable) are skipped.
    """
    toks: list[tuple[str, str]] = []  # (kind, text); kind: s=string, p=punct, w=word
    for m in _TOKEN_RE.finditer(text):
        if m.group(1) is not None:
            toks.append(("s", m.group(1).replace('\\"', '"')))
        elif m.group(2):
            toks.append(("p", m.group(2)))
        else:
            toks.append(("w", m.group(3)))

    pos = 0

    def block(depth: int) -> dict[str, dict[str, object]]:
        nonlocal pos
        res: dict[str, dict[str, object]] = {}
        while pos < len(toks):
            kind, tx = toks[pos]
            if kind == "p" and tx == "}":
                pos += 1
                return res
            if kind != "w":
                pos += 1
                continue
            nxt = toks[pos + 1] if pos + 1 < len(toks) else ("", "")
            if nxt == ("p", "{"):                    # container: NAME {
                pos += 2
                inner = block(depth + 1)
                if depth == 0:                       # a variable (or NC_GLOBAL)
                    res[tx] = {k: v for k, v in inner.get("__attrs__", {}).items()}
                continue
            # attribute: TYPE NAME value[, value ...];
            name = toks[pos + 1][1] if pos + 1 < len(toks) else ""
            pos += 2
            vals: list[tuple[str, str]] = []
            while pos < len(toks) and toks[pos] != ("p", ";"):
                if toks[pos][0] != "p":
                    vals.append(toks[pos])
                pos += 1
            pos += 1
            attrs = res.setdefault("__attrs__", {})
            if tx in ("String", "Url"):
                attrs[name] = " ".join(v for _, v in vals)
            else:
                nums = []
                for _, v in vals:
                    try:
                        nums.append(float(v))
                    except ValueError:
                        pass
                attrs[name] = nums
        return res

    # skip "Attributes {"
    while pos < len(toks) and toks[pos] != ("p", "{"):
        pos += 1
    pos += 1
    return block(0)


def _attr_num(attrs: dict[str, object], key: str) -> float | None:
    v = attrs.get(key)
    if isinstance(v, list) and v:
        return v[0]
    return None


def is_packed(attrs: dict[str, object]) -> bool:
    """True when the variable carries a scale_factor / add_offset that changes the
    values (anything but 1 / 0). Present-but-unreadable counts as packed: we cannot
    show it is harmless."""
    for key, identity in (("scale_factor", 1.0), ("add_offset", 0.0)):
        if key not in attrs:
            continue
        v = _attr_num(attrs, key)
        if v is None or not math.isfinite(v) or v != identity:
            return True
    return False


def _attr_str(attrs: dict[str, object], key: str) -> str | None:
    v = attrs.get(key)
    return v if isinstance(v, str) and v.strip() else None


# ──────────────────────────── time ──────────────────────────────────────────

_UNIT_SECONDS = {
    "day": 86400.0, "days": 86400.0, "d": 86400.0,
    "hour": 3600.0, "hours": 3600.0, "hr": 3600.0, "h": 3600.0,
    "minute": 60.0, "minutes": 60.0, "min": 60.0,
    "second": 1.0, "seconds": 1.0, "sec": 1.0, "s": 1.0,
}
_TIME_UNITS_RE = re.compile(
    r"^\s*([A-Za-z]+)\s+since\s+(\d{4})-(\d{1,2})-(\d{1,2})"
    r"(?:[T\s]+(\d{1,2}):(\d{2})(?::(\d{2})(\.\d+)?)?)?\s*(Z|UTC|GMT|[+-]\d{2}:?\d{2})?\s*$"
)


def parse_time_units(units: str | None, calendar: str | None = None) -> tuple[datetime, float]:
    """``(origin, seconds_per_unit)`` from a CF time ``units`` attribute.

    Read from the file, never assumed: the GDAC mostly says
    ``days since 1950-01-01T00:00:00Z`` but nothing obliges a file to.
    """
    if calendar and calendar.strip().lower() not in ("standard", "gregorian", "proleptic_gregorian"):
        raise UnsupportedFile(f"calendar {calendar!r}")
    m = _TIME_UNITS_RE.match(units or "")
    if not m or m.group(1).lower() not in _UNIT_SECONDS:
        raise UnsupportedFile(f"time units {units!r}")
    y, mo, d = int(m.group(2)), int(m.group(3)), int(m.group(4))
    hh, mi = int(m.group(5) or 0), int(m.group(6) or 0)
    ss = float(f"{m.group(7) or 0}{m.group(8) or ''}")
    tz = timezone.utc
    z = m.group(9)
    if z and z[0] in "+-":
        digits = z[1:].replace(":", "")
        off = timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))
        tz = timezone(off if z[0] == "+" else -off)
    origin = datetime(y, mo, d, hh, mi, tzinfo=tz) + timedelta(seconds=ss)
    return origin.astimezone(timezone.utc), _UNIT_SECONDS[m.group(1).lower()]


def decode_time(value: float, origin: datetime, unit_seconds: float) -> datetime | None:
    if value is None or not math.isfinite(value):
        return None
    try:
        return origin + timedelta(seconds=round(value * unit_seconds, 3))
    except (OverflowError, ValueError):
        return None


# ──────────────────────────── ASCII ─────────────────────────────────────────

_ASCII_HEAD_RE = re.compile(r"^(\w+)((?:\[\d+\])+)\s*$")


def parse_ascii(text: str) -> dict[str, list[float]]:
    """``{NAME: flat values in C order}`` from an OPeNDAP .ascii response.

    The shape of each array is in the response's own header (parse it with
    :func:`parse_dds`); rows are ``[i][j][k], v1, v2, ...`` with the indices
    stripped and the values running along the last dimension, or a bare
    comma-separated line for a 1-D array. ``NaN`` stays NaN.
    """
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        raise OpendapError("rejected", "no ASCII payload separator")
    body = parts[1].split("\n", 1)[1] if "\n" in parts[1] else ""
    out: dict[str, list[float]] = {}
    cur: list[float] | None = None
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            cur = None
            continue
        h = _ASCII_HEAD_RE.match(line)
        if h and cur is None:
            cur = out.setdefault(h.group(1), [])
            continue
        if cur is None:
            continue
        if line.startswith("["):
            line = line.split(",", 1)[1] if "," in line else ""
        for tok in line.split(","):
            tok = tok.strip()
            if tok:
                cur.append(float(tok))
    return out


# ──────────────────────────── plan + request ────────────────────────────────


def is_depth_dim(name: str) -> bool:
    """``DEPTH`` or a per-variable ``DEPTH_<VAR>`` axis (PAPA files carry DEPTH_TEMP,
    DEPTH_PSAL, ... each with its own coordinate variable of the same name).
    ``BINDEPTH`` / ``CELL`` (ADCP range bins, depth moving with time) are NOT depth."""
    return name.upper().startswith("DEPTH")


def ceil_div(a: int, b: int) -> int:
    return -(-a // b)


@dataclass
class VarPlan:
    name: str
    qc_name: str | None
    decl: VarDecl
    qc_decl: VarDecl | None
    std_name: str
    units: str | None
    long_name: str | None
    fills: tuple[float, ...]
    qc_fills: tuple[float, ...]
    n_time: int
    stride: int
    depth_axis: int | None            # position in dims, None = no depth dimension
    depth_step: int
    depth_indices: list[int]


@dataclass
class Plan:
    time_origin: datetime
    time_unit_s: float
    vars: list[VarPlan]
    skipped: list[tuple[str, str]]    # (variable, reason)
    citation: str | None


def _fills(attrs: dict[str, object]) -> tuple[float, ...]:
    out = []
    for k in ("_FillValue", "missing_value"):
        v = attrs.get(k)
        if isinstance(v, list):
            out.extend(v)
    return tuple(out)


def _find_qc(name: str, attrs: dict[str, object], dds: dict[str, VarDecl]) -> str | None:
    """The QC variable of ``name``.

    ``<NAME>_QC`` first. ``ancillary_variables`` is only a fallback, and only when
    it names a QC variable that does not belong to a different data variable:
    in the real K276 file VCUR's ``ancillary_variables`` says ``UCUR_QC``, and
    trusting it would grade the northward velocity with the eastward flags.
    """
    own = f"{name}_QC"
    if own in dds:
        return own
    anc = attrs.get("ancillary_variables")
    if isinstance(anc, str):
        for tok in anc.split():
            if tok.endswith("_QC") and tok in dds and (tok[:-3] == name or tok[:-3] not in dds):
                return tok
    return None


def plan_file(dds: dict[str, VarDecl], das: dict[str, dict[str, object]],
              wanted: frozenset[str] | set[str]) -> Plan:
    """Decide what to read. Raises :class:`UnsupportedFile` when nothing is usable."""
    tname = next((n for n in dds if n.upper() == "TIME"), None)
    if tname is None or not dds[tname].dims:
        raise UnsupportedFile("no TIME variable")
    tdecl = dds[tname]
    tattrs = das.get(tname, {})
    origin, unit_s = parse_time_units(_attr_str(tattrs, "units"), _attr_str(tattrs, "calendar"))
    n_time = tdecl.dims[0][1]
    glob = das.get("NC_GLOBAL", {})

    vars_: list[VarPlan] = []
    skipped: list[tuple[str, str]] = []
    for name, decl in dds.items():
        attrs = das.get(name, {})
        std = _attr_str(attrs, "standard_name")
        if std not in wanted or name == tname:
            continue
        if name.endswith("_QC"):
            continue
        if is_packed(attrs):
            skipped.append((name, PACKED_REASON))
            continue
        t_axis = next((i for i, (dn, _) in enumerate(decl.dims) if dn.upper() == "TIME"), None)
        if t_axis is None or decl.dims[t_axis][1] != n_time:
            skipped.append((name, "no TIME axis of the file's length"))
            continue
        d_axis = next((i for i, (dn, _) in enumerate(decl.dims) if is_depth_dim(dn)), None)
        bad = [dn for i, (dn, sz) in enumerate(decl.dims)
               if i not in (t_axis, d_axis) and sz != 1]
        if bad:
            skipped.append((name, f"extra axis {bad[0]} larger than 1"))
            continue
        if n_time <= 0:
            skipped.append((name, "no samples"))
            continue
        qc = _find_qc(name, attrs, dds)
        nd = decl.dims[d_axis][1] if d_axis is not None else 1
        step = ceil_div(nd, MAX_DEPTHS)
        vars_.append(VarPlan(
            name=name, qc_name=qc, decl=decl, qc_decl=dds.get(qc) if qc else None,
            std_name=std, units=_attr_str(attrs, "units"), long_name=_attr_str(attrs, "long_name"),
            fills=_fills(attrs), qc_fills=_fills(das.get(qc, {})) if qc else (),
            n_time=n_time, stride=ceil_div(n_time, MAX_SAMPLES),
            depth_axis=d_axis, depth_step=step, depth_indices=list(range(0, nd, step)),
        ))
    if not vars_:
        packed = [n for n, why in skipped if why == PACKED_REASON]
        reasons = list(dict.fromkeys(why for _, why in skipped))
        raise UnsupportedFile(
            "no wanted variable usable" + (f" ({'; '.join(reasons)})" if reasons else ""), packed)
    return Plan(origin, unit_s, vars_, skipped, _attr_str(glob, "citation"))


def _slice(decl: VarDecl, p: VarPlan) -> str:
    """Index ranges by dimension NAME (a QC variable may order its axes differently)."""
    parts = []
    for dn, sz in decl.dims:
        if dn.upper() == "TIME":
            parts.append(f"[0:{p.stride}:{sz - 1}]")
        elif is_depth_dim(dn):
            parts.append(f"[0:{p.depth_step}:{sz - 1}]")
        else:
            parts.append("[0:1:0]")
    return "".join(parts)


def _item(decl: VarDecl, p: VarPlan) -> str:
    sl = _slice(decl, p)
    return f"{decl.name}.{decl.name}{sl}" if decl.grid else f"{decl.name}{sl}"


def build_constraint(plan: Plan, dds: dict[str, VarDecl], only: list[VarPlan] | None = None) -> str:
    """The one ``.ascii?`` constraint: TIME, the DEPTH axis, every variable + QC."""
    vs = only if only is not None else plan.vars
    tname = next(n for n in dds if n.upper() == "TIME")
    first = vs[0]
    items = [f"{tname}[0:{first.stride}:{first.n_time - 1}]"]
    depth_names: set[str] = set()
    for p in vs:
        if p.depth_axis is not None:
            dn, sz = p.decl.dims[p.depth_axis]
            if dn in dds and dn not in depth_names:
                depth_names.add(dn)
                items.append(f"{dn}[0:{p.depth_step}:{sz - 1}]")
        else:
            dn = next((n for n in dds if n.upper() == "DEPTH"), None)
            if dn and dn not in depth_names and dds[dn].dims and dds[dn].dims[0][1] == 1:
                depth_names.add(dn)
                items.append(dn)
        items.append(_item(p.decl, p))
        if p.qc_decl is not None:
            items.append(_item(p.qc_decl, p))
    return ",".join(dict.fromkeys(items))  # a repeated reference is a 400


# ──────────────────────────── decode ────────────────────────────────────────


def is_fill(v: float | None, fills: tuple[float, ...]) -> bool:
    """Declared fill (compared at float32 precision, as stored), or not a number.

    ⛔ The ``abs(v) >= 1e30`` clause is deliberate and rests on evidence: the real TAO
    file OS_T0N140W_DM092A-20140916_D_TEMP_10min.nc declares ``_FillValue -999.0`` yet
    carries ``1.0E33`` on the 500 m level, flagged QC 4 by its producer. Declared fills
    alone would store 1e33 as a temperature. Nothing smaller is guessed: 99999 / -999
    are fill only where the file says so."""
    if v is None or not math.isfinite(v) or abs(v) >= 1e30:
        return True
    for f in fills:
        if not math.isfinite(f):
            continue
        if v == f or abs(v - f) <= 1e-6 * max(1.0, abs(f)):
            return True
    return False


@dataclass
class SeriesRow:
    variable: str
    depth_index: int
    depth_m: float | None
    units: str | None
    long_name: str | None
    standard_name: str
    n_total: int
    stride: int
    times: list[datetime]
    vals: list[float | None]
    qc: list[int | None]
    first_time: datetime
    last_time: datetime


@dataclass
class FileFetch:
    series: list[SeriesRow] = field(default_factory=list)
    citation: str | None = None
    skipped: list[tuple[str, str]] = field(default_factory=list)
    requests: int = 0
    fills_nulled: int = 0
    # Variables whose read was answered this time (even if every level was fill):
    # what the new read replaces. A variable the server refused is NOT in here.
    variables_read: set[str] = field(default_factory=set)


def _qc_value(v: float, fills: tuple[float, ...]) -> int | None:
    if not math.isfinite(v) or abs(v) >= 1e30 or any(v == f for f in fills):
        return None
    r = round(v)
    return int(r) if abs(v - r) < 1e-6 and 0 <= r <= 9 else None


def decode_response(plan: Plan, text: str, only: list[VarPlan] | None = None) -> tuple[list[SeriesRow], int]:
    """Turn an .ascii body into series rows. Fill -> None; QC stored beside the value."""
    shapes = parse_dds(text.split("\n---", 1)[0])
    data = parse_ascii(text)
    tname = next((n for n in shapes if n.upper() == "TIME"), None)
    if tname is None or tname not in data:
        raise OpendapError("rejected", "TIME missing from the response")
    raw_times = data[tname]
    times = [decode_time(t, plan.time_origin, plan.time_unit_s) for t in raw_times]
    rows: list[SeriesRow] = []
    nulled = 0
    for p in (only if only is not None else plan.vars):
        if p.name not in data:
            raise OpendapError("rejected", f"{p.name} missing from the response")
        t_axis = next(i for i, (dn, _) in enumerate(p.decl.dims) if dn.upper() == "TIME")
        shape = [sz for _, sz in shapes[p.name].dims]
        vals = data[p.name]
        if (len(shape) != len(p.decl.dims) or math.prod(shape) != len(vals)
                or shape[t_axis] != len(raw_times)):
            raise OpendapError("rejected", f"{p.name}: payload does not match its declared shape")
        qvals = None
        if p.qc_name and p.qc_name in data:
            qvals = data[p.qc_name]
            if len(qvals) != len(vals):
                raise OpendapError("rejected", f"{p.qc_name}: QC payload does not match its variable")
        nt = shape[t_axis]
        nd = shape[p.depth_axis] if p.depth_axis is not None else 1
        if nd != len(p.depth_indices):
            raise OpendapError("rejected", f"{p.name}: depth axis does not match the request")
        # C-order strides of the response array
        strides = [1] * len(shape)
        for i in range(len(shape) - 2, -1, -1):
            strides[i] = strides[i + 1] * shape[i + 1]
        depth_vals: list[float] | None = None
        if p.depth_axis is not None:
            dn = p.decl.dims[p.depth_axis][0]
            if dn in data and len(data[dn]) == nd:
                depth_vals = data[dn]
        else:
            dkey = next((n for n in data if n.upper() == "DEPTH"), None)
            if dkey and len(data[dkey]) == 1:
                depth_vals = data[dkey]
        for j in range(nd):
            ts: list[datetime] = []
            vs: list[float | None] = []
            qs: list[int | None] = []
            for i in range(nt):
                t = times[i]
                if t is None:
                    continue
                off = i * strides[t_axis] + (j * strides[p.depth_axis] if p.depth_axis is not None else 0)
                v = vals[off]
                if is_fill(v, p.fills):
                    vs.append(None)
                    nulled += 1
                else:
                    vs.append(v)
                qs.append(_qc_value(qvals[off], p.qc_fills) if qvals is not None else None)
                ts.append(t)
            good = [t for t, v in zip(ts, vs) if v is not None]
            if not good:
                continue  # an instrument level with nothing in the sample: nothing to store
            dm = None
            if depth_vals is not None and not is_fill(depth_vals[j], ()):
                dm = depth_vals[j]
            rows.append(SeriesRow(
                variable=p.name, depth_index=p.depth_indices[j] if p.depth_axis is not None else 0,
                depth_m=dm, units=p.units, long_name=p.long_name, standard_name=p.std_name,
                n_total=p.n_time, stride=p.stride, times=ts, vals=vs, qc=qs,
                first_time=good[0], last_time=good[-1],
            ))
    return rows, nulled


# ──────────────────────────── HTTP ──────────────────────────────────────────


def file_url(file: str) -> str:
    """OPeNDAP URL of a catalogue file (``DATA/<dir>/<name>.nc``)."""
    return f"{OPENDAP_BASE}/{urllib.parse.quote(file, safe='/')}"


async def _get(client: httpx.AsyncClient, url: str, counter: list[int]) -> str:
    """GET with a short retry on 5xx / transport errors. Never returns an error body."""
    last: Exception | None = None
    for attempt in range(_RETRIES):
        counter[0] += 1
        try:
            r = await client.get(url, timeout=HTTP_TIMEOUT, follow_redirects=True)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last = OpendapError("unavailable", f"{type(exc).__name__}")
        else:
            if r.status_code == 200:
                if REQUEST_DELAY:
                    await asyncio.sleep(REQUEST_DELAY)
                return r.content.decode("latin-1")
            if r.status_code >= 500 or r.status_code == 429:
                last = OpendapError("unavailable", f"HTTP {r.status_code}")
            else:
                raise OpendapError("rejected", f"HTTP {r.status_code}")
        if attempt + 1 < _RETRIES:
            await asyncio.sleep(_RETRY_DELAY * (attempt + 1))
    assert last is not None
    raise last


async def fetch_file_series(client: httpx.AsyncClient, file: str,
                            wanted: frozenset[str] | set[str]) -> FileFetch:
    """Sample the wanted variables of one GDAC file.

    Raises :class:`OpendapError` (``unavailable`` = outage, ``rejected`` = this
    file/constraint is refused) or :class:`UnsupportedFile`; the caller counts it
    and leaves whatever is stored alone. Returns an empty ``series`` only when
    the file was read and every sampled level was fill.
    """
    base = file_url(file)
    counter = [0]
    dds = parse_dds(await _get(client, base + ".dds", counter))
    das = parse_das(await _get(client, base + ".das", counter))
    plan = plan_file(dds, das, wanted)
    out = FileFetch(citation=plan.citation, skipped=list(plan.skipped))
    try:
        q = urllib.parse.quote(build_constraint(plan, dds), safe="")
        text = await _get(client, f"{base}.ascii?{q}", counter)
        out.series, out.fills_nulled = decode_response(plan, text)
        out.variables_read = {p.name for p in plan.vars}
    except OpendapError as exc:
        if exc.kind != "rejected" or len(plan.vars) == 1:
            raise
        # One variable's odd shape must not cost the others: ask one by one.
        for p in plan.vars:
            try:
                q = urllib.parse.quote(build_constraint(plan, dds, [p]), safe="")
                text = await _get(client, f"{base}.ascii?{q}", counter)
                rows, nulled = decode_response(plan, text, [p])
            except OpendapError as exc2:
                if exc2.kind != "rejected":
                    raise
                out.skipped.append((p.name, f"constraint refused: {exc2}"))
                continue
            out.series.extend(rows)
            out.fills_nulled += nulled
            out.variables_read.add(p.name)
    out.requests = counter[0]
    return out


# ──────────────────────────── selection + change marker ─────────────────────


def valid_stamp(ts: datetime | None) -> bool:
    """A GDAC stamp is usable if it is a plausible date (the ALOHA rows carry junk)."""
    return ts is not None and 1990 <= ts.year <= datetime.now(timezone.utc).year + 1


def change_marker(row: dict) -> str | None:
    """What says "this file changed since I sampled it".

    ``gdac_update_date`` when valid, else ``date_update``, else size + end time;
    ``None`` when the catalogue offers none of them (then a file is fetched only
    once, never because of a marker that does not exist).
    """
    g, d = row.get("gdac_update_date"), row.get("date_update")
    if valid_stamp(g):
        return "g:" + g.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if valid_stamp(d):
        return "d:" + d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    size, end = row.get("size_bytes"), row.get("end_time")
    if size is not None and end is not None:
        return f"s:{size}:{end.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    return None


def select_files(candidates: list[dict], limit: int = MAX_FILES_PER_SERIES) -> dict[str, tuple[int, set[str]]]:
    """Choose the files to sample, bounded per (station, variable).

    ``candidates``: dicts with ``station_ref, file, data_mode, start_time,
    end_time, parameters`` (the link table joined to the catalogue). For every
    (station, standard_name in HISTORY_STANDARD_NAMES) the files whose
    PARAMETERS carry that name are ranked D > M > P > R, then by duration, and
    taken greedily, skipping a file whose span is already covered by the ones
    chosen, up to ``limit``. Files with no usable span come last and only fill
    spare places. Returns ``{file: (best_rank, {standard names to read})}``
    where ``best_rank`` is the position the file held in its best selection —
    0 = somebody's first pick — so a capped run can serve every station its
    best file before anybody's second.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for c in candidates:
        for name in c.get("parameters") or ():
            if name in HISTORY_STANDARD_NAMES:
                groups.setdefault((c["station_ref"], name), []).append(c)

    def sort_key(c: dict):
        s, e = c.get("start_time"), c.get("end_time")
        dur = (e - s).total_seconds() if s and e and e >= s else -1.0
        return (dur < 0, _MODE_RANK.get(c.get("data_mode") or "", 4), -dur, c["file"])

    chosen: dict[str, tuple[int, set[str]]] = {}
    for (_ref, name), files in groups.items():
        covered: list[tuple[datetime, datetime]] = []
        picked = 0
        for c in sorted(files, key=sort_key):
            if picked >= limit:
                break
            s, e = c.get("start_time"), c.get("end_time")
            if s and e and e >= s:
                if any(cs <= s and e <= ce for cs, ce in covered):
                    continue
                covered = _merge(covered + [(s, e)])
            rank = picked
            picked += 1
            prev = chosen.get(c["file"])
            if prev is None:
                chosen[c["file"]] = (rank, {name})
            else:
                prev[1].add(name)
                chosen[c["file"]] = (min(prev[0], rank), prev[1])
    return chosen


def _merge(iv: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    out: list[tuple[datetime, datetime]] = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


SETTLED_NO_DATA = ("empty", "refused")


def plan_run(candidates: list[dict], fetched: dict[str, dict], max_files: int) -> dict:
    """What this run should fetch, in order, and what is left over.

    ``candidates``: link rows joined to the catalogue (see :func:`select_files`,
    plus ``size_bytes``, ``gdac_update_date``, ``date_update``). ``fetched``:
    ``{file: {outcome, change_marker, standard_names}}`` from
    ``oceansites_gdac_fetched``.

    * a file read before with the same change marker (or any marker, when the
      catalogue has none to offer) is not read again — unless it now has to
      serve a standard name it was not read for;
    * a file settled as ``empty`` (nothing sampleable) or ``refused`` (the server
      answered 4xx) is left alone until its change marker moves, and does not
      occupy one of a station's 30 places;
    * the files are ordered by the place they hold in their best selection, so
      a capped first run gives every mooring its best file before anyone gets a
      second one.
    """
    info: dict[str, dict] = {}
    for c in candidates:
        info.setdefault(c["file"], c)

    def unchanged(f: str) -> bool:
        log_row = fetched.get(f)
        if log_row is None:
            return False
        cur = change_marker(info[f])
        return cur is None or log_row.get("change_marker") == cur

    live = [c for c in candidates
            if not (fetched.get(c["file"], {}).get("outcome") in SETTLED_NO_DATA and unchanged(c["file"]))]
    chosen = select_files(live)
    todo: list[tuple[int, str, set[str]]] = []
    for f, (rank, names) in chosen.items():
        log_row = fetched.get(f)
        if log_row and unchanged(f) and names <= set(log_row.get("standard_names") or ()):
            continue
        todo.append((rank, f, names))
    todo.sort(key=lambda t: (t[0], t[1]))
    return {
        "selected": len(chosen),
        "needed": len(todo),
        "todo": [(f, names) for _, f, names in todo[:max_files]],
        "remaining": max(0, len(todo) - max_files),
    }
