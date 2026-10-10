# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""SOCATv2026 streaming parser — no database, no network. Reads the tab-separated synthesis file
line by line and yields, per cruise (the file is ordered by Expocode, one contiguous block each):

* `Segment`      — the point level: a run of consecutive rows (<= SEG_MAX_OBS, no long pause, no
                   antimeridian crossing, <= SEG_MAX_SPAN_DEG wide) with ALL its rows, rejected ones included;
* `LodPiece`     — the overview levels 0..3: the same track reduced to the grid cells it passed through,
                   built from WOCE-2 rows only, with the mean of the values;
* `CruiseSummary`— one per cruise, after its segments and pieces.

Memory is independent of the cruise length: only the open segment and one open piece per level are held.
A missing value is NaN in the segment arrays (array('d') cannot hold None) and None in a LodPiece."""
from __future__ import annotations
import io
import math
import zipfile
from array import array
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Iterator, TextIO

from ingestion import socat_points_rules as R

_NAN = float("nan")
MEMBER = "SOCATv2026.tsv"
_N_COLS = len(R.EXPECTED_HEADER)
_TABLE_COLS = 15
_TABLE_END_PREFIXES = ("Note for data set", "Explanation of data columns")


class SchemaError(Exception):
    """The file is not the one the rules were measured on: refuse to import rather than guess."""


@dataclass
class CruiseMeta:
    expocode: str
    version: str | None
    dataset_name: str | None
    platform_name: str | None
    pis: str | None
    source_doi: str | None
    source_reference: str | None
    qc_flag: str
    metadata_docs: str | None


@dataclass
class Segment:
    expocode: str
    qc_flag: str
    ord0: int                 # 0-based ordinal of the first row within the cruise (all rows counted)
    t0: datetime              # UTC time of the first row
    lon: array                # folded to -180..180
    lat: array                # as in the file (up to 90.0); the bbox is clamped in SQL
    dt_s: array               # seconds since t0
    fco2: array               # NaN = missing
    sst: array
    sal: array
    fco2_src: array           # algorithm 0-14, -1 = missing
    fco2_flag: array          # WOCE flag, -1 = missing


@dataclass
class LodPiece:
    level: int
    expocode: str
    qc_flag: str
    n0: int                   # 0-based ordinal of the piece's first WOCE-2 row within the cruise
    n_obs: int                # WOCE-2 rows in the piece
    year: int                 # UTC year; a piece never spans a year boundary
    fco2: float | None        # means over the non-missing values only
    sst: float | None
    sal: float | None
    vertices: list[tuple[float, float]]    # (lon, lat) after fold + Mercator clamp


@dataclass
class CruiseSummary:
    expocode: str
    n_obs: int
    n_segments: int
    first_time: datetime
    last_time: datetime
    west: float
    east: float
    south: float
    north: float
    crosses_antimeridian: bool            # west > east: the cruise's box wraps over +-180
    n_rejected: int                       # rows with a dataset flag outside A-D or WOCE != 2


def _na(token: str) -> str | None:
    t = token.strip()
    return None if t in ("", "N/A") else t


def read_dataset_table(lines: Iterable[str]) -> dict[str, CruiseMeta]:
    """The per-dataset table that precedes the data: 15 tab-separated fields per line, between the
    column line (starts with "Expocode<TAB>", no `yr` column) and the explanatory text block."""
    out: dict[str, CruiseMeta] = {}
    in_table = False
    for raw in lines:
        line = raw.rstrip("\r\n")
        if not in_table:
            if line.startswith("Expocode\t") and "\tyr\t" not in line:
                in_table = True
            elif line.startswith("Expocode\t"):
                break              # reached the data header without ever seeing a dataset table
            continue
        if not line or line.startswith(_TABLE_END_PREFIXES) or line.startswith("Expocode\t"):
            break
        f = line.split("\t")
        if len(f) != _TABLE_COLS:
            raise SchemaError(f"dataset table line with {len(f)} fields (expected {_TABLE_COLS}): {line[:80]!r}")
        out[f[0]] = CruiseMeta(
            expocode=f[0], version=_na(f[1]), dataset_name=_na(f[2]), platform_name=_na(f[3]),
            pis=_na(f[4]), source_doi=_na(f[5]), source_reference=_na(f[6]),
            qc_flag=f[13].strip(), metadata_docs=_na(f[14]))
    if not in_table:
        raise SchemaError("dataset table header not found")
    return out


def open_member(zip_path) -> TextIO:
    """The synthesis TSV inside the NCEI zip, as text. newline="" keeps line ends untouched (we strip them)."""
    zf = zipfile.ZipFile(zip_path)
    return io.TextIOWrapper(zf.open(MEMBER), encoding="utf-8", newline="")


class _Piece:
    __slots__ = ("qc", "n0", "n_obs", "year", "verts", "cx", "cy",
                 "s_fco2", "c_fco2", "s_sst", "c_sst", "s_sal", "c_sal")

    def __init__(self, qc, n0, year, verts, cx, cy):
        self.qc, self.n0, self.year, self.verts, self.cx, self.cy = qc, n0, year, verts, cx, cy
        self.n_obs = 0
        self.s_fco2 = self.s_sst = self.s_sal = 0.0
        self.c_fco2 = self.c_sst = self.c_sal = 0

    def close(self, level: int, expocode: str) -> LodPiece:
        return LodPiece(
            level=level, expocode=expocode, qc_flag=self.qc, n0=self.n0, n_obs=self.n_obs, year=self.year,
            fco2=self.s_fco2 / self.c_fco2 if self.c_fco2 else None,
            sst=self.s_sst / self.c_sst if self.c_sst else None,
            sal=self.s_sal / self.c_sal if self.c_sal else None,
            vertices=self.verts)


class _Cruise:
    """State machine for one cruise block."""

    def __init__(self, expocode: str):
        self.expocode = expocode
        self.n = 0
        self.n_rejected = 0
        self.n_segments = 0
        self.seg: Segment | None = None
        self.seg_lon = (0.0, 0.0)      # min, max of the open segment
        self.seg_lat = (0.0, 0.0)
        self.pieces: list[_Piece | None] = [None] * len(R.LOD_CELLS)
        self.prev_t: datetime | None = None
        self.prev_lon = 0.0
        self.inc_t: datetime | None = None      # previous WOCE-2 row (pieces ignore the others)
        self.inc_lon = 0.0
        self.first_t: datetime | None = None
        self.last_t: datetime | None = None
        self.south = 91.0
        self.north = -91.0
        self.u_lon = 0.0               # longitude unwrapped along the track, for the cruise bbox
        self.u_min = 0.0
        self.u_max = 0.0

    def add(self, f: list[str]) -> list:
        try:
            t = R.obs_time(f[4], f[5], f[6], f[7], f[8], f[9])
            lon_raw = R.num(f[10])
            lat = R.num(f[11])
            sal = R.num(f[13])
            sst = R.num(f[14])
            fco2 = R.num(f[29])
            src = int(float(f[30]))
            flag = int(float(f[31]))
        except (ValueError, OverflowError) as e:
            raise SchemaError(f"unparseable row in {self.expocode} (row {self.n}): {e}") from e
        if lon_raw is None or lat is None or not -90.0 <= lat <= 90.0:
            raise SchemaError(f"row {self.n} of {self.expocode} has no usable position: {f[10]!r}, {f[11]!r}")
        lon = R.normalize_lon(lon_raw)
        qc = f[3]
        idx = self.n
        self.n += 1
        out: list = []
        rejected = qc not in R.GOOD_QC or flag != R.GOOD_WOCE
        if rejected:
            self.n_rejected += 1

        # ── cruise summary state
        if idx == 0:
            self.first_t = self.last_t = t
            self.u_lon = self.u_min = self.u_max = lon
        else:
            if t < self.first_t:
                self.first_t = t
            if t > self.last_t:
                self.last_t = t
            d = lon - self.prev_lon
            if d > 180.0:
                d -= 360.0
            elif d < -180.0:
                d += 360.0
            self.u_lon += d
            if self.u_lon < self.u_min:
                self.u_min = self.u_lon
            elif self.u_lon > self.u_max:
                self.u_max = self.u_lon
        if lat < self.south:
            self.south = lat
        if lat > self.north:
            self.north = lat

        # ── segment: every row, rejected included
        seg = self.seg
        if seg is not None:
            lo, hi = self.seg_lon
            la, lb = self.seg_lat
            if (len(seg.lon) >= R.SEG_MAX_OBS
                    or abs((t - self.prev_t).total_seconds()) > R.SEG_MAX_GAP_S
                    or R.crosses_antimeridian(self.prev_lon, lon)
                    or max(hi, lon) - min(lo, lon) > R.SEG_MAX_SPAN_DEG
                    or max(lb, lat) - min(la, lat) > R.SEG_MAX_SPAN_DEG):
                out.append(seg)
                seg = None
        if seg is None:
            seg = self.seg = Segment(
                expocode=self.expocode, qc_flag=qc, ord0=idx, t0=t,
                lon=array("d"), lat=array("d"), dt_s=array("d"), fco2=array("d"), sst=array("d"),
                sal=array("d"), fco2_src=array("b"), fco2_flag=array("b"))
            self.n_segments += 1
            self.seg_lon = (lon, lon)
            self.seg_lat = (lat, lat)
        else:
            self.seg_lon = (min(self.seg_lon[0], lon), max(self.seg_lon[1], lon))
            self.seg_lat = (min(self.seg_lat[0], lat), max(self.seg_lat[1], lat))
        seg.lon.append(lon)
        seg.lat.append(lat)
        seg.dt_s.append((t - seg.t0).total_seconds())
        seg.fco2.append(_NAN if fco2 is None else fco2)
        seg.sst.append(_NAN if sst is None else sst)
        seg.sal.append(_NAN if sal is None else sal)
        seg.fco2_src.append(src)
        seg.fco2_flag.append(flag)

        # ── LOD pieces: WOCE-2 rows only (the dataset flag is carried on the piece and filtered by the tiles)
        if flag == R.GOOD_WOCE:
            self._add_to_pieces(out, t, lon, lat, qc, idx, fco2, sst, sal)
            self.inc_t = t
            self.inc_lon = lon
        self.prev_t = t
        self.prev_lon = lon
        return out

    def _add_to_pieces(self, out, t, lon, lat, qc, idx, fco2, sst, sal) -> None:
        lat_c = max(-R.MERC_LAT, min(R.MERC_LAT, lat))
        year = t.year
        hard_break = False
        if self.inc_t is not None:
            hard_break = (abs((t - self.inc_t).total_seconds()) > R.PIECE_MAX_GAP_S
                          or R.crosses_antimeridian(self.inc_lon, lon))
        for lv, cell in enumerate(R.LOD_CELLS):
            cx = math.floor(lon / cell)
            cy = math.floor(lat_c / cell)
            p = self.pieces[lv]
            carried = None
            if p is not None:
                if hard_break or year != p.year:
                    out.append(p.close(lv, self.expocode))
                    p = None
                elif cx != p.cx or cy != p.cy:
                    if max(abs(cx - p.cx), abs(cy - p.cy)) > R.PIECE_JUMP_CELLS:
                        out.append(p.close(lv, self.expocode))
                        p = None
                    elif len(p.verts) >= R.PIECE_MAX_VERTICES[lv]:
                        # vertex cap: close and start the next piece AT the last vertex, so the lines join
                        out.append(p.close(lv, self.expocode))
                        carried = p.verts[-1]
                        p = None
                    else:
                        p.verts.append((lon, lat_c))
                        p.cx, p.cy = cx, cy
            if p is None:
                verts = [carried, (lon, lat_c)] if carried is not None else [(lon, lat_c)]
                p = self.pieces[lv] = _Piece(qc, idx, year, verts, cx, cy)
            p.n_obs += 1
            if fco2 is not None:
                p.s_fco2 += fco2
                p.c_fco2 += 1
            if sst is not None:
                p.s_sst += sst
                p.c_sst += 1
            if sal is not None:
                p.s_sal += sal
                p.c_sal += 1

    def finish(self) -> list:
        out: list = []
        if self.seg is not None:
            out.append(self.seg)
        for lv, p in enumerate(self.pieces):
            if p is not None:
                out.append(p.close(lv, self.expocode))
        if self.u_max - self.u_min >= 360.0:
            west, east = -180.0, 180.0
        else:
            west, east = R.normalize_lon(self.u_min), R.normalize_lon(self.u_max)
        out.append(CruiseSummary(
            expocode=self.expocode, n_obs=self.n, n_segments=self.n_segments,
            first_time=self.first_t, last_time=self.last_t, west=west, east=east,
            south=self.south, north=self.north, crosses_antimeridian=west > east,
            n_rejected=self.n_rejected))
        return out


def iter_records(text_stream) -> Iterator[Segment | LodPiece | CruiseSummary]:
    """Stream the records of every cruise in a SOCAT synthesis file (or its excerpt), in file order."""
    it = iter(text_stream)
    header_line = None
    for line in it:
        if line.startswith("Expocode\t") and "\tyr\t" in line:
            header_line = line
            break
    if header_line is None:
        raise SchemaError("data header line (Expocode<TAB>...<TAB>yr<TAB>...) not found")
    header = tuple(header_line.rstrip("\r\n").split("\t"))
    if header != R.EXPECTED_HEADER:
        diff = [(i, a, b) for i, (a, b) in enumerate(zip(header, R.EXPECTED_HEADER)) if a != b]
        raise SchemaError(f"header differs from the measured one ({len(header)} columns): {diff[:3]}")

    seen: set[str] = set()
    cur: _Cruise | None = None
    for raw in it:
        line = raw.rstrip("\r\n")
        if not line:
            continue
        f = line.split("\t")
        if len(f) != _N_COLS:
            raise SchemaError(f"data line with {len(f)} fields (expected {_N_COLS}): {line[:80]!r}")
        expo = f[0]
        if cur is None or expo != cur.expocode:
            if cur is not None:
                yield from cur.finish()
            if expo in seen:
                raise SchemaError(f"{expo} reappears after another cruise: the file is no longer one block per cruise")
            seen.add(expo)
            cur = _Cruise(expo)
        out = cur.add(f)
        if out:
            yield from out
    if cur is not None:
        yield from cur.finish()
