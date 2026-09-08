# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""When a thaw feature was actually observed — pulled out of the imagery string.

Both permafrost sources date every feature, and both were having that date folded
into a free-text `imagery` blob where nothing could query it. Verified at the live
sources on 2026-09-08:

  ARTS v6.0.0        `BaseMapDate` = "2020-07-05,2020-08-20"   (present on every
                     feature in the sampled 4,069) plus `ContributionDate`
  Alaska Webb v2.0   `ImageryDates` = "1950-01-01 through 2015-12-31" or
                     "1985 through 2015"  (17,245 of 19,540 = 88%)

⛔ THIS IS AN IMAGERY WINDOW, NOT A SAMPLING DAY. A retrogressive thaw slump is
mapped from imagery spanning a period; the feature was not observed on one date
and the source never claims it was. So the precision here tops out at `campaign`
and the two bounds are what matter.

⛔ A bare year stays a year. "1985 through 2015" does NOT become 1985-01-01 —
that is the precision inflation `docs/methods/data-passthrough.md` forbids, and it
would be invisible: 1985-01-01 looks like a real observation date. Years go in the
*_year columns, full dates additionally in the DATE columns, and a consumer can
tell which it got by whether the DATE is null.
"""
from __future__ import annotations

import datetime as _dt
import re

_NA = {"", "n/a", "na", "none", "null", "-", "nan", "unknown"}

# ARTS separates its pair with a comma; Alaska Webb writes "A through B". Both are
# the same shape — two bounds — so they get one parser rather than two that drift.
_SPLIT = re.compile(r"\s+through\s+|\s*,\s*|\s*;\s*", re.IGNORECASE)

_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_YEAR = re.compile(r"^(\d{4})$")


class Window:
    """(start_year, end_year, start_date, end_date, precision) with a name."""
    __slots__ = ("start_year", "end_year", "start_date", "end_date", "precision")

    def __init__(self, start_year=None, end_year=None,
                 start_date=None, end_date=None, precision="none"):
        self.start_year = start_year
        self.end_year = end_year
        self.start_date = start_date
        self.end_date = end_date
        self.precision = precision

    def as_tuple(self):
        return (self.start_year, self.end_year,
                self.start_date, self.end_date, self.precision)

    def __eq__(self, other):
        return isinstance(other, Window) and self.as_tuple() == other.as_tuple()

    def __repr__(self):
        return f"Window{self.as_tuple()}"


def _one_bound(token: str):
    """(year, date|None) for a single bound, or (None, None) if unusable."""
    token = token.strip()
    m = _ISO.match(token)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        try:
            return y, _dt.date(y, mo, d)
        except ValueError:
            # A date the source wrote that is not a real calendar date. Keep the
            # year — it is still an anchor — and drop only the impossible part.
            return y, None
    m = _YEAR.match(token)
    if m:
        y = int(m.group(1))
        # A four-digit number outside instrumental range is a field with something
        # else in it, not a year we should trust.
        return (y, None) if 1700 <= y <= 2100 else (None, None)
    return None, None


def parse_observation_window(raw) -> Window:
    """Parse an imagery-date field from either permafrost source.

    Returns a Window whose `precision` is:
      "campaign" — two usable bounds (the normal case for both sources)
      "day"      — one bound and it is a full calendar date
      "year"     — one bound and it is only a year
      "none"     — nothing usable, including a blank or an N/A placeholder
    """
    if raw is None:
        return Window()
    text = str(raw).strip()
    if text.lower() in _NA:
        return Window()

    bounds = [b for b in _SPLIT.split(text) if b.strip()]
    parsed = [_one_bound(b) for b in bounds]
    usable = [(y, d) for (y, d) in parsed if y is not None]
    if not usable:
        return Window()

    if len(usable) == 1:
        y, d = usable[0]
        # One acquisition, not a window: the feature really was mapped from imagery
        # of that day (or that year, if the day is all the source gave).
        return Window(start_year=y, end_year=y, start_date=d, end_date=d,
                      precision="day" if d else "year")

    # More than two bounds has not been seen at either source; if it appears, the
    # outermost pair is the honest window rather than a parse failure.
    (sy, sd) = usable[0]
    (ey, ed) = usable[-1]
    if sy > ey:                      # written backwards — bounds are a set, not an order
        (sy, sd), (ey, ed) = (ey, ed), (sy, sd)
    return Window(start_year=sy, end_year=ey, start_date=sd, end_date=ed,
                  precision="campaign")


def parse_single_date(raw) -> "_dt.date | None":
    """A lone ISO date — ARTS `ContributionDate`.

    ⛔ NOT an observation date. It records when the digitisation was contributed,
    which can be years after the imagery was taken (2024 for imagery from 2020 in
    the sampled data). Stored separately so it can never be mistaken for one.
    """
    if raw is None:
        return None
    m = _ISO.match(str(raw).strip())
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    try:
        return _dt.date(y, mo, d)
    except ValueError:
        return None


def window_fields(raw) -> dict:
    """`parse_observation_window` as the five column values, ready to splat into a
    row dict. Keeps both ingests from spelling the same five keys twice and drifting."""
    w = parse_observation_window(raw)
    return {
        "obs_start_year": w.start_year,
        "obs_end_year":   w.end_year,
        "obs_start":      w.start_date,
        "obs_end":        w.end_date,
        "date_precision": w.precision,
    }
