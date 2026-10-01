# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Shared reader for PANGAEA `?format=textfile` exports and their JSON-LD.

Shape confirmed on 2026-09-25 against two real downloads, never from memory:

* The file opens with `/* DATA DESCRIPTION:` and the block closes on a line that
  is exactly `*/`. The next line is the tab-separated header, then one line per
  row, LF only, ending with a final LF.
* `Size:\\t<N> data points` counts non-empty PARAMETER cells, not rows. The
  geocode columns (Date/Time, Latitude, Longitude, Elevation, Depth water) and
  Event labels are not counted. CoastDOM v1: 70,823 rows, 1,286,555 data points.
  Greenland Sea PP: 12 rows, 12 data points. So completeness is proven by the
  data-point count, never by comparing rows with Size.
* The dataset citation is the block's `Citation:` line and the related
  publication its `Supplement to:` line. The JSON-LD carries neither as text; it
  carries `datePublished`, `license` and `size` (the same data-point count).

⛔ Cells are never stripped or unquoted. 672 CoastDOM cells carry leading or
trailing whitespace (a location ends in an NBSP) and 5,796 contain double quotes,
so a csv reader with quoting would silently rewrite them. Split on TAB only.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
from dataclasses import dataclass
from types import ModuleType
from typing import Iterator


class PangaeaFormatError(ValueError):
    """The download is not the PANGAEA table that was verified. The sync aborts
    and the stored version stays exactly as it was."""


_OPEN = "/* DATA DESCRIPTION:"
_CLOSE = "*/"


@dataclass(frozen=True)
class PangaeaFile:
    meta: dict[str, str]
    header: tuple[str, ...]
    body_lines: list[str]
    size_data_points: int | None


@dataclass(frozen=True)
class JsonLdMeta:
    identifier: str | None
    date_published: _dt.date | None
    license: str | None
    size_data_points: int | None


def split_pangaea(text: str) -> PangaeaFile:
    if not text.startswith(_OPEN):
        raise PangaeaFormatError(f"not a PANGAEA textfile: starts with {text[:40]!r}")
    if not text.endswith("\n"):
        raise PangaeaFormatError("file does not end with a newline - truncated download")
    lines = text.split("\n")[:-1]
    try:
        close = lines.index(_CLOSE)
    except ValueError:
        raise PangaeaFormatError("comment block is never closed with '*/'") from None
    if close + 1 >= len(lines):
        raise PangaeaFormatError("no header line after the comment block")
    meta: dict[str, str] = {}
    for ln in lines[1:close]:
        # Continuation lines (the Parameter(s) and Event(s) lists) start with a TAB.
        if ln.startswith("\t") or ":\t" not in ln:
            continue
        key, _, value = ln.partition(":\t")
        meta.setdefault(key, value)
    size = None
    if "Size" in meta:
        count, _, unit = meta["Size"].partition(" ")
        if unit != "data points" or not count.isdigit():
            raise PangaeaFormatError(f"unexpected Size line: {meta['Size']!r}")
        size = int(count)
    return PangaeaFile(meta=meta, header=tuple(lines[close + 1].split("\t")),
                       body_lines=lines[close + 2:], size_data_points=size)


def check_header(header: tuple[str, ...], expected: tuple[str, ...]) -> None:
    """Refuse any header that is not byte-identical to the verified one. Columns
    are resolved by position; a renamed unit or a shifted column would otherwise
    load plausible numbers under the wrong parameter."""
    if tuple(header) != tuple(expected):
        diffs = [(i, got, want) for i, (got, want) in enumerate(zip(header, expected)) if got != want]
        raise PangaeaFormatError(
            f"header differs from the verified one ({len(header)} vs {len(expected)} columns); "
            f"first differences: {diffs[:3]}"
        )


def iter_rows(pf: PangaeaFile) -> Iterator[tuple[int, tuple[str, ...]]]:
    n = len(pf.header)
    for row_no, line in enumerate(pf.body_lines, start=1):
        cells = tuple(line.split("\t"))
        if len(cells) != n:
            raise PangaeaFormatError(f"row {row_no}: {len(cells)} cells, header has {n}")
        yield row_no, cells


def coerce(kind: str, cell: str, *, row_no: int, column: str):
    """Empty cell → None for every kind (a missing value is NULL, never 0).
    Anything that does not parse raises: a surprise means the source changed."""
    if cell == "":
        return None
    if kind == "text":
        return cell
    if kind == "float":
        try:
            v = float(cell)
        except ValueError:
            raise PangaeaFormatError(f"row {row_no} {column!r}: {cell!r} is not a number") from None
        if not math.isfinite(v):
            raise PangaeaFormatError(f"row {row_no} {column!r}: {cell!r} is not finite")
        return v
    if kind == "flag":
        if not cell.isdigit():
            raise PangaeaFormatError(f"row {row_no} {column!r}: quality flag {cell!r} is not an integer")
        return int(cell)
    if kind == "date":
        if len(cell) != 10 or cell[4] != "-" or cell[7] != "-":
            raise PangaeaFormatError(f"row {row_no} {column!r}: {cell!r} is not YYYY-MM-DD")
        try:
            return _dt.date.fromisoformat(cell)
        except ValueError:
            raise PangaeaFormatError(f"row {row_no} {column!r}: {cell!r} is not a date") from None
    raise ValueError(f"unknown column kind {kind!r}")


def count_data_points(cells: tuple[str, ...], positions: frozenset[int]) -> int:
    return sum(1 for i in positions if cells[i] != "")


def parse_row(columns: tuple[tuple[str, str], ...], header: tuple[str, ...],
              row_no: int, cells: tuple[str, ...]) -> dict:
    """Generic positional row parser shared by every PANGAEA parser module.
    `columns` is (database column, kind) per source position; `header` is the
    verified header, used only so error messages name the source column."""
    rec: dict = {"row_no": row_no}
    for (name, kind), col_header, cell in zip(columns, header, cells):
        rec[name] = coerce(kind, cell, row_no=row_no, column=col_header)
    rec["raw"] = list(cells)
    return rec


def is_mappable(rec: dict) -> bool:
    """A row is mappable when it has both coordinates. Shared because every
    PANGAEA water-column layer resolves position the same way."""
    return rec["lat"] is not None and rec["lon"] is not None


def validate(parser: ModuleType, pf: PangaeaFile, jsonld_points: int | None) -> tuple[int, int, int]:
    """Parse every row once, without touching the database, and prove the file is
    whole. Returns (rows, unmappable rows, data points)."""
    check_header(pf.header, parser.EXPECTED_HEADER)
    rows = unmappable = points = 0
    for row_no, cells in iter_rows(pf):
        rec = parser.parse_row(row_no, cells)
        rows += 1
        points += count_data_points(cells, parser.DATA_POINT_POSITIONS)
        if not parser.is_mappable(rec):
            unmappable += 1
    if rows == 0:
        raise PangaeaFormatError("no data rows")
    if pf.size_data_points is None:
        raise PangaeaFormatError("no Size line - the file cannot prove it is complete")
    if points != pf.size_data_points:
        raise PangaeaFormatError(
            f"{points} data points counted, the file's own Size line states "
            f"{pf.size_data_points} - truncated or reshaped"
        )
    if jsonld_points is not None and jsonld_points != pf.size_data_points:
        raise PangaeaFormatError(
            f"JSON-LD states {jsonld_points} data points, the file {pf.size_data_points} - "
            "the two were fetched from different versions"
        )
    return rows, unmappable, points


def parse_jsonld(raw: bytes) -> JsonLdMeta:
    try:
        d = json.loads(raw)
    except ValueError as exc:
        raise PangaeaFormatError(f"JSON-LD is not JSON: {exc}") from None
    if not isinstance(d, dict) or d.get("@type") != "Dataset":
        raise PangaeaFormatError("JSON-LD is not a schema.org Dataset")
    date = None
    dp = d.get("datePublished")
    if isinstance(dp, str) and len(dp) >= 10:
        try:
            date = _dt.date.fromisoformat(dp[:10])
        except ValueError:
            date = None
    size = d.get("size")
    points = None
    if isinstance(size, dict) and size.get("unitText") == "data points" \
            and isinstance(size.get("value"), (int, float)):
        points = int(size["value"])
    lic = d.get("license")
    ident = d.get("identifier")
    return JsonLdMeta(
        identifier=ident if isinstance(ident, str) else None,
        date_published=date,
        license=lic if isinstance(lic, str) else None,
        size_data_points=points,
    )
