# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Fetch Ocean Networks Canada observatory station locations from Oceans 3.0 API.

API docs: https://wiki.oceannetworks.ca/spaces/O2A/pages/49447542/API+Guide
Token: set ONC_TOKEN env var (register free at https://data.oceannetworks.ca/Registration)
License: CC BY 4.0
"""
import asyncio
import logging
import os
import httpx

log = logging.getLogger(__name__)

ONC_BASE = "https://data.oceannetworks.ca/api"
ONC_TOKEN = os.getenv("ONC_TOKEN", "")

# Fallback list, used only if the live GET /deviceCategories?method=get call
# fails (transient outage). Deliberately small — this degrades the ingest to
# "the two categories we always had", not "nothing".
_FALLBACK_CATEGORIES = ["CTD", "OXYSENSOR"]

# Delay between successive per-category location calls. Measured 2026-09-08:
# fetching every category is ~129 calls where it used to be 2 — pace them so
# we don't hammer ONC in a tight loop.
_REQUEST_PACE_SECONDS = 0.15


def safe_exc(exc: BaseException) -> str:
    """A log-safe rendering of an httpx exception.

    ⛔ NEVER log the raw exception from an ONC call. httpx puts the full request
    URL in str(exc), and every ONC request carries ?token=<ONC_TOKEN>. The
    root-logger filter in log_redaction.py does catch it — but a credential
    must not depend on one backstop, and that filter only matches secrets that
    were present in the environment when it was installed.
    """
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


async def fetch_device_categories(client: httpx.AsyncClient) -> list[str] | None:
    """Fetch the live list of ONC device category codes.

    Measured 2026-09-08: GET /deviceCategories?method=get returns 129
    categories.

    Returns None on ANY failure (network error, non-2xx, empty body) — this
    is a deliberate signal distinct from "fetched successfully". A caller
    that silently substituted `_FALLBACK_CATEGORIES` here and treated the
    result as if it were live data is exactly the bug that let one timed-out
    call truncate ~1,993 locations down to ~183 (2026-09-08 audit). Callers
    that want the fallback list applied must do so explicitly and must know
    they did.
    """
    try:
        resp = await client.get(
            f"{ONC_BASE}/deviceCategories",
            params={"method": "get", "token": ONC_TOKEN},
        )
        resp.raise_for_status()
        data = resp.json()
        codes = [
            d.get("deviceCategoryCode")
            for d in data
            if isinstance(d, dict) and d.get("deviceCategoryCode")
        ]
        if codes:
            return codes
        log.warning("onc: deviceCategories returned no codes")
    except httpx.HTTPStatusError as exc:
        # str(exc) embeds the full request URL, including ?token=... —
        # log_redaction.py catches this today, but don't rely on it: log
        # only the status code, never the raw exception object.
        status = exc.response.status_code if exc.response is not None else "?"
        log.warning("onc: deviceCategories fetch failed (HTTP %s)", status)
    except Exception as exc:
        log.warning("onc: deviceCategories fetch failed (%s)", type(exc).__name__)
    return None


async def fetch_onc_locations() -> tuple[list[dict], list[tuple[str, str]], bool]:
    """Fetch every ONC observatory location, across every device category.

    Queries GET /deviceCategories?method=get for the current category list,
    then GET /locations?method=getByDeviceCategory for each category in turn,
    deduplicating locations by location_code.

    A 404 on a category is EXPECTED (measured 2026-09-08: 9 of 129 categories
    return 404, e.g. MAGNETOMETER, PIES, PONECAMERA, SERVER) — it means the
    category currently has zero locations. Skip it, count it, keep going;
    never abort the sync over one category's 404.

    CORRECTED 2026-09-08: an earlier version of this module excluded
    AISRECEIVER as "~1,800 AIS shore stations". Measured against the real
    API: `getByDeviceCategory(AISRECEIVER)` returns 126 locations. The 1,800
    figure belongs to a different, unrelated endpoint — the bare
    `locations?method=get` call — and never applied to the per-category
    query this module makes. AIS is no longer excluded; every category is
    fetched.

    Returns (locations, location_categories, categories_ok):
      - locations: deduplicated list of dicts (location_code, name, lat, lon,
        depth_m, description) — one row per unique location, ~1,993 measured.
      - location_categories: (location_code, device_category_code) pairs —
        one row per (location, category) it was found under, ~4,937 measured.
        This is the new information; do not throw it away by deduplicating it.
      - categories_ok: False if the live deviceCategories fetch failed and
        this call fell back to `_FALLBACK_CATEGORIES` (2 categories instead
        of ~129). Callers MUST treat `categories_ok=False` as "this result is
        not a true widening of the ingest" and must not let it replace a
        larger, previously-stored location set.
    """
    if not ONC_TOKEN:
        log.warning("ONC_TOKEN not set — skipping ONC ingestion")
        return [], [], False

    seen: set[str] = set()
    locations: list[dict] = []
    location_categories: list[tuple[str, str]] = []
    no_data_categories = 0

    async with httpx.AsyncClient(timeout=30) as client:
        categories = await fetch_device_categories(client)
        categories_ok = categories is not None
        if categories is None:
            log.warning("onc: deviceCategories unavailable — falling back to %s", _FALLBACK_CATEGORIES)
            categories = list(_FALLBACK_CATEGORIES)

        for i, category in enumerate(categories):
            if i > 0:
                await asyncio.sleep(_REQUEST_PACE_SECONDS)
            try:
                resp = await client.get(
                    f"{ONC_BASE}/locations",
                    params={
                        "method":             "getByDeviceCategory",
                        "deviceCategoryCode": category,
                        "token":              ONC_TOKEN,
                    },
                )
                if resp.status_code == 404:
                    # Normal: the category currently has zero locations.
                    no_data_categories += 1
                    continue
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    no_data_categories += 1
                    continue
                # str(exc) embeds the request URL including ?token=... — log
                # the status code, never the raw exception.
                status = exc.response.status_code if exc.response is not None else "?"
                log.warning("onc: category %s fetch failed (HTTP %s)", category, status)
                continue
            except Exception as exc:
                log.warning("onc: category %s fetch failed (%s)", category, type(exc).__name__)
                continue

            if not data:
                no_data_categories += 1
                continue

            for item in data:
                code = item.get("locationCode", "")
                if not code:
                    continue
                location_categories.append((code, category))
                if code in seen:
                    continue
                lat = item.get("lat")
                lon = item.get("lon")
                if lat is None or lon is None:
                    continue
                seen.add(code)
                depth = item.get("depth")
                locations.append({
                    "location_code": code,
                    "name":          item.get("locationName", ""),
                    "lat":           float(lat),
                    "lon":           float(lon),
                    "depth_m":       float(depth) if depth is not None else None,
                    "description":   item.get("description", "") or "",
                })

    log.info(
        "onc: fetched %d unique locations, %d (location, category) pairs "
        "from %d categories (%d of %d categories returned no locations, "
        "categories_ok=%s)",
        len(locations), len(location_categories), len(categories),
        no_data_categories, len(categories), categories_ok,
    )
    return locations, location_categories, categories_ok
