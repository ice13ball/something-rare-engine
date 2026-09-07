# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Shared value-parsing leaf helpers.

Moved out of main.py (Task 3 of the backend vertical-split refactor). Imports
only stdlib + `ingestion.date_sentinels` (itself a stdlib-only leaf), so any
domain module or router can depend on this without creating an import cycle
back into main.py.
"""

from ingestion.date_sentinels import is_placeholder_date


def coerce_date(v):
    """Convert ISO strings or ArcGIS epoch-ms integers to datetime.date.

    Every date reaching `offshore_activities` funnels through here (see
    `_offshore_upsert`), so this is the one place that drops upstream fill
    values. The raw value survives verbatim in `attributes`.
    """
    out = v
    if isinstance(v, (int, float)):
        try:
            from datetime import datetime as _dt
            out = _dt.utcfromtimestamp(v / 1000).date()
        except (ValueError, OSError):
            return None
    elif isinstance(v, str) and v:
        try:
            from datetime import date as _date
            out = _date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None if is_placeholder_date(out) else out
