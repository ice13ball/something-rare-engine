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


class ArcGISError(RuntimeError):
    """An ArcGIS REST endpoint answered with an `error` body instead of data."""


class ArcGISTokenRequired(ArcGISError):
    """The service went private (code 498/499). Needs a human, not a retry."""


def arcgis_features(body: dict, label: str = "") -> list[dict]:
    """Return `features` from an ArcGIS query response, or raise.

    ⛔ ArcGIS reports errors as HTTP 200 with `{"error": {...}}`, so
    `raise_for_status()` never fires and `.get("features", [])` turns "this
    service now requires a token" into "this source has no features". That is
    how ANP Brazil and GNPC Ghana sat stale for weeks in October 2026 under a
    "no features with geometry" skip. A body without a `features` key is not
    an empty answer either — an empty answer still carries `"features": []`.
    """
    err = body.get("error") if isinstance(body, dict) else None
    if err:
        code = err.get("code")
        msg = f"{label or 'arcgis'}: error {code} {err.get('message')!r}"
        if code in (498, 499):
            raise ArcGISTokenRequired(msg)
        raise ArcGISError(msg)
    if not isinstance(body, dict) or "features" not in body:
        raise ArcGISError(f"{label or 'arcgis'}: response has no 'features' key")
    return body["features"]
