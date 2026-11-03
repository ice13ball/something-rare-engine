# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The date chain of an OBIS record, shared with the plankton model (its plan, section 1.4).

Pure functions, no I/O, so the extract child and the loader can both import it cheaply. The atlas and the
plankton model must never give one record two dates: parse/pair_stats/is_proven are the model's datefmt.py
verbatim, except that spaces around an interval's slash are allowed here, and resolve_date is its FINAL_SQL date
CASE, row by row. Change them together.

Order: the date OBIS itself read, then the Darwin Core year/month/day fields, then a lenient reading of
eventDate, only for forms whose field order is certain. Ambiguous strings never beat explicit fields, and a
day-first form is read only when the first number is > 12 or the (dataset x pattern) pair is proven.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass

PROOF_MIN_FIRST_GT12 = 20

_TIME = re.compile(
    r"^(?P<date>.*?)[T ](?P<h>\d{1,2}):(?P<mi>\d\d)(?::(?P<s>\d\d)(?:[.,]\d+)?)?"
    r"\s*(?:Z|UTC|[+-]\d\d(?::?\d\d)?)?$")
_YMD_FIRST = re.compile(r"^(\d{4})(?:([-/.])(\d{1,2})(?:\2(\d{1,2}))?)?$")
_ISO_END = re.compile(r"^\d{4}(?:-\d\d(?:-\d\d)?)?(?:[T ].*)?$")
_DMY_LAST = re.compile(r"^(\d{1,2})([./-])(\d{1,2})\2(\d{4})$")

KIND_YMD_FIRST = "ymd_first"
KIND_INTERVAL = "interval"
KIND_DMY_LAST = "dmy_last"
KIND_OTHER = "other"


@dataclass(frozen=True)
class Parsed:
    kind: str
    pattern: str
    year: int | None = None
    month: int | None = None
    day: int | None = None
    first: int | None = None    # dmy_last only: first number
    second: int | None = None   # dmy_last only: second number
    ambiguous: bool = False     # dmy_last with both numbers in 1..12
    source: str = "eventdate_lenient"


def pattern_of(s: str) -> str:
    return re.sub(r"\d", "9", s)


def _split_time(s: str) -> tuple[str, bool]:
    """Return (date part, time_ok). A string with a time must have a valid one
    (hour <= 24, 24 only as 24:00[:00]); T24:00 keeps its own date part."""
    m = _TIME.match(s)
    if not m:
        return s, True
    h, mi, sec = int(m["h"]), int(m["mi"]), int(m["s"] or 0)
    ok = (h < 24 and mi < 60 and sec < 61) or (h == 24 and mi == 0 and sec == 0)
    return m["date"], ok


def _valid(y: int, m: int | None, d: int | None) -> bool:
    if not 1000 <= y <= 2200:
        return False
    if m is None:
        return d is None
    if not 1 <= m <= 12:
        return False
    return d is None or 1 <= d <= calendar.monthrange(y, m)[1]


def _ymd_first(date: str):
    """(y, m, d) or None for one year-first date without time."""
    m = _YMD_FIRST.match(date)
    if not m:
        return None
    y = int(m[1])
    mo = int(m[3]) if m[3] else None
    d = int(m[4]) if m[4] else None
    return (y, mo, d) if _valid(y, mo, d) else None


def parse(raw: str | None, proven_dm: bool = False) -> Parsed | None:
    """Parse one raw eventDate. None for null/empty input."""
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    pat = pattern_of(s)

    # ISO interval "A/B": both ends year-first with hyphens
    if s.count("/") == 1:
        left, right = (end.strip() for end in s.split("/"))   # `2016-01-23 / 2016-02-16` (ab46e252)
        if _ISO_END.match(left) and _ISO_END.match(right):
            (ld, lok), (rd, rok) = _split_time(left), _split_time(right)
            a, b = _ymd_first(ld), _ymd_first(rd)
            if not (lok and rok and a and b):
                return Parsed(KIND_INTERVAL, pat)
            y = a[0] if a[0] == b[0] else None
            mo = a[1] if y and a[1] is not None and a[1] == b[1] else None
            d = a[2] if mo and a[2] is not None and a[2] == b[2] else None
            return Parsed(KIND_INTERVAL, pat, y, mo, d)

    date, tok = _split_time(s)

    ymd = _ymd_first(date) if tok else None
    if _YMD_FIRST.match(date):
        if not tok or ymd is None:
            return Parsed(KIND_YMD_FIRST, pat)
        return Parsed(KIND_YMD_FIRST, pat, *ymd)

    m = _DMY_LAST.match(date)
    if m:
        a, b, y = int(m[1]), int(m[3]), int(m[4])
        if not tok or not 1000 <= y <= 2200:
            return Parsed(KIND_DMY_LAST, pat, first=a, second=b)
        if a > 12 and 1 <= b <= 12 and _valid(y, b, a):
            return Parsed(KIND_DMY_LAST, pat, y, b, a, a, b)
        if 1 <= a <= 12 and 1 <= b <= 12:
            if proven_dm and _valid(y, b, a):
                return Parsed(KIND_DMY_LAST, pat, y, b, a, a, b, True,
                              "eventdate_dataset_dm")
            return Parsed(KIND_DMY_LAST, pat, y, None, None, a, b, True)
        if 1 <= a <= 12 and b > 12:
            return Parsed(KIND_DMY_LAST, pat, y, None, None, a, b)  # M/D: year only
        return Parsed(KIND_DMY_LAST, pat, first=a, second=b)        # nonsense: nothing
    return Parsed(KIND_OTHER, pat)


def pair_stats(items: list[tuple[Parsed, int]]) -> dict[str, dict]:
    """Per pattern: counts of first>12, second>12, both<=12 (weights = row counts)."""
    out: dict[str, dict] = {}
    for p, n in items:
        if p.kind != KIND_DMY_LAST:
            continue
        st = out.setdefault(p.pattern, {"first_gt12": 0, "second_gt12": 0,
                                        "both_le12": 0, "rows": 0})
        st["rows"] += n
        if p.first is not None and p.first > 12:
            st["first_gt12"] += n
        if p.second is not None and p.second > 12:
            st["second_gt12"] += n
        if (p.first is not None and p.second is not None
                and 1 <= p.first <= 12 and 1 <= p.second <= 12):
            st["both_le12"] += n
    return out


def is_proven(st: dict, is_compilation: bool) -> bool:
    return (not is_compilation and st["first_gt12"] >= PROOF_MIN_FIRST_GT12
            and st["second_gt12"] == 0)


# --------------------------------------------------------------------------- the chain

DATE_SOURCES = ("obis", "dwc_fields", "eventdate_lenient", "eventdate_dataset_dm", "none")
COMPILATION_PATTERN = r"world ocean database|compilation|wod ?(19|20)\d\d|nodc"
_COMPILATION_RE = re.compile(COMPILATION_PATTERN, re.I)
YEAR_MIN, YEAR_MAX = 1000, 2200
# Cheap SQL prefilter for the proof: only strings that can be year-last ever reach parse().
YEAR_LAST_SQL_RE = r"^\s*\d{1,2}[./-]\d{1,2}[./-]\d{4}"
YEAR_LAST_MAX_LEN = 40        # longer than any date with a time and an offset: never read, never held in memory


def is_compilation(title: str | None) -> bool:
    """A compilation mixes sources, so one source's day-first habit proves nothing about the others."""
    return bool(_COMPILATION_RE.search(title or ""))


def add_pair_stats(into: dict[str, dict], counts) -> None:
    """Fold (raw eventDate, rows) into per-pattern statistics; memory grows with patterns, not with strings."""
    items = [(p, n) for p, n in ((parse(raw), n) for raw, n in counts) if p]
    for pat, st in pair_stats(items).items():
        total = into.setdefault(pat, {k: 0 for k in st})
        for k, v in st.items():
            total[k] += v


def proven_patterns(stats: dict[str, dict], compilation: bool) -> frozenset[str]:
    """Year-last patterns of ONE dataset whose day-first order is proven, from add_pair_stats()."""
    return frozenset(pat for pat, st in stats.items() if is_proven(st, compilation))


def to_int(value) -> int | None:
    """Same result as DuckDB's TRY_CAST(value AS INTEGER), which the model uses on these fields."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return round(float(str(value).strip()))
    except (TypeError, ValueError, OverflowError):
        return None


@dataclass(frozen=True)
class ResolvedDate:
    year: int | None
    month: int | None
    day: int | None
    source: str


NO_DATE = ResolvedDate(None, None, None, "none")


def resolve_date(*, date_start=None, date_end=None, date_year=None, event_date=None, obis_event_date=None,
                 year=None, month=None, day=None, proven: frozenset[str] = frozenset()) -> ResolvedDate:
    """date_start/date_end: dt.date, as OBIS read them. event_date: the raw source string. year/month/day:
    the Darwin Core fields, interpreted value first. `proven`: this dataset's proven_patterns()."""
    t24 = "T24:" in (event_date if event_date is not None else obis_event_date or "")
    lv = None
    if event_date is not None:
        lv = parse(event_date)
        if lv is not None and lv.kind == KIND_DMY_LAST and lv.pattern in proven:
            lv = parse(event_date, True)
    lv_y, lv_m, lv_d = (lv.year, lv.month, lv.day) if lv else (None, None, None)
    lv_src = lv.source if lv else "eventdate_lenient"

    # T24:00 shifts OBIS's own date to the next day; the string's date part is the day that was sampled.
    if t24 and lv_d is not None:
        return ResolvedDate(lv_y, lv_m, lv_d, lv_src)

    o_y = o_m = o_d = None
    if date_start is not None and date_end is not None:
        if date_start.year == date_end.year:
            o_y = date_start.year
            if date_start.month == date_end.month:
                o_m = date_start.month
        if date_start == date_end:
            o_d = date_start.day
    else:
        o_y = to_int(date_year)
        o_y = o_y if o_y is not None and YEAR_MIN <= o_y <= YEAR_MAX else None   # year is a SMALLINT column
    if not t24 and o_y is not None:
        return ResolvedDate(o_y, o_m, o_d, "obis")

    y_dwc = to_int(year)
    y_dwc = y_dwc if y_dwc is not None and YEAR_MIN <= y_dwc <= YEAR_MAX else None
    m_dwc = to_int(month) if y_dwc is not None else None
    m_dwc = m_dwc if m_dwc is not None and 1 <= m_dwc <= 12 else None
    d_dwc = to_int(day) if m_dwc is not None else None
    if d_dwc is not None and not 1 <= d_dwc <= calendar.monthrange(y_dwc, m_dwc)[1]:
        d_dwc = None

    if y_dwc is not None and m_dwc is not None:
        return ResolvedDate(y_dwc, m_dwc, d_dwc, "dwc_fields")
    if lv_m is not None and (y_dwc is None or y_dwc == lv_y):
        return ResolvedDate(lv_y, lv_m, lv_d, lv_src)
    if y_dwc is not None:
        return ResolvedDate(y_dwc, None, None, "dwc_fields")
    if lv_y is not None:
        return ResolvedDate(lv_y, None, None, "eventdate_lenient")
    return NO_DATE
