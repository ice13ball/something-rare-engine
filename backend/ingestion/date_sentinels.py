# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Placeholder dates published by upstream registries.

Some ArcGIS-hosted registries emit a date for fields that are simply unknown.
Ghana's GNPC service sends `-2209161600000` epoch-ms — serial 0 of the Excel /
OLE Automation date epoch (1899-12-30), i.e. an empty spreadsheet cell that
picked up a date type on its way into ArcGIS.

We keep the provider's raw value verbatim in `offshore_activities.attributes`
(`Start_date` / `End_date`), and store NULL in the typed `awarded_date` /
`expires_date` columns rather than presenting a fill as a fact. Same policy as
`_NA_SENTINELS` in `deepdata_dwc_ingest.py`.

Why it matters beyond cosmetics: a sentinel of 1899-12-30 precedes every
observation ever recorded, so any `awarded_date <= sample_time` temporal-
precedence join silently adopts these licences as the oldest — and therefore
default — candidate cause for anything nearby.
"""
import datetime as dt

#: Excel / OLE Automation serial 0, as ArcGIS epoch milliseconds.
EPOCH_SENTINEL_MS = -2209161600000

#: Dates that are known fills, never real award/expiry dates.
_PLACEHOLDER_DATES = frozenset({dt.date(1899, 12, 30)})


def is_placeholder_date(d: dt.date | None) -> bool:
    """True only for a known upstream fill value.

    `None` is already absent, not a sentinel, so it returns False — callers
    should not need to special-case it.
    """
    return d is not None and d in _PLACEHOLDER_DATES
