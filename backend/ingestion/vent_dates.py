# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""`hydrothermal_vents.discovery_year` as InterRidge actually writes it: free text,
not a year. Verified on production 2026-09-08: 721/721 rows non-null, 691 begin
with a clean 4-digit year (min 1800, max 2018). The other 30 are 29x the literal
string "NotProvided" and one multi-event string,
"nearshore: since antiquity; offshore: 1997 SCUBA".

This module adds a machine-readable year beside the text — it does not replace it.
`discovery_year` (the raw text) keeps reaching the popup and the SEO vent report
unchanged; see `docs/methods/data-passthrough.md` for the `date_precision`
vocabulary this follows. Only two of its five levels can occur here: "year" and
"none" — InterRidge never gives a month or day for a discovery, and this layer has
no cruise-window concept, so "month", "day" and "campaign" are unreachable.

⛔ ONLY A LEADING YEAR COUNTS. "nearshore: since antiquity; offshore: 1997 SCUBA"
describes two events centuries apart; pulling 1997 out of the middle would
silently discard "since antiquity" and assert a precision nobody gave us. That
row — and any string whose first token is not a 4-digit year — is (None, "none").

⛔ A year is never widened into a date. No 1 January: see the parser's rules
above, the same rule `thaw_dates.parse_observation_window` follows for permafrost.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re

log = logging.getLogger(__name__)

_MIN_YEAR = 1750

_LEADING_YEAR = re.compile(r"^(\d{4})\b")


def parse_discovery_year(raw: str | None) -> tuple[int | None, str]:
    """(year, date_precision) for one `discovery_year` free-text value.

    Rules:
      - A leading 4-digit year in [1750, current_year + 1] -> (year, "year").
      - `NotProvided`, empty/None, or anything with no leading year -> (None, "none").
      - A leading year outside that range -> (None, "none"), logged at WARNING
        with the raw string — that means the source changed shape.
    """
    if raw is None:
        return None, "none"
    text = raw.strip()
    if not text or text == "NotProvided":
        return None, "none"

    m = _LEADING_YEAR.match(text)
    if not m:
        return None, "none"

    year = int(m.group(1))
    max_year = _dt.date.today().year + 1
    if not (_MIN_YEAR <= year <= max_year):
        log.warning("vent_dates: leading year %d out of plausible range in %r", year, raw)
        return None, "none"

    return year, "year"
