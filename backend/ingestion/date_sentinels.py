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


#: Epoch zeros that a spreadsheet or a Unix conversion leaves behind when a
#: date was never entered. ⛔ NOT usable as a global rule — see the warning on
#: `is_epoch_fill_date`.
_EPOCH_FILL_DATES = frozenset({dt.date(1900, 1, 1), dt.date(1970, 1, 1)})


def is_epoch_fill_date(d: dt.date | None) -> bool:
    """True for a date that is an epoch zero rather than a sampling day.

    ⛔ **Never apply this blindly to a new source.** `1970-01-01` is a real
    day and some sources really did sample on it. Proved on 2026-09-10:

      wod_oxygen_profiles   1970-01-01 -> 19 rows, neighbouring days 18-38,
                            and a by-id fetch returns a real 7-level profile.
                            REAL. This function must not touch WOD.

      mosaic_cores          1900-01-01 -> 49 rows, and ZERO cores anywhere in
                            1896-1935 beside them; 1970-01-01 -> 6 rows with
                            no neighbour within eight days. Decisive extra
                            evidence: 25 of the 55 carry campaign_name
                            "1980-1993", so the core cannot have been taken
                            in 1900. FILL.

    The test that separates them is the same both times: look at the
    NEIGHBOURHOOD and at what else the row says about itself. A spike with no
    shoulders, or a date that contradicts its own campaign, is a fill.
    """
    return d is not None and d in _EPOCH_FILL_DATES


def is_placeholder_date(d: dt.date | None) -> bool:
    """True only for a known upstream fill value.

    `None` is already absent, not a sentinel, so it returns False — callers
    should not need to special-case it.
    """
    return d is not None and d in _PLACEHOLDER_DATES
