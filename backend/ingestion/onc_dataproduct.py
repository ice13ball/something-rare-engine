# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Async client for ONC's `dataProductDelivery` order API.

Unlike `scalardata/location` (synchronous, scalar sensors only), data products are
*ordered*: `request` → `run` → poll `status` → `download`. This is the only route to
depth-resolved ADCP data; see `onc_adcp_product` for why.

`adcp_device_category_code` is pure and unit-tested. The rest is I/O.
"""
from __future__ import annotations

import asyncio
import logging
import re

import httpx

log = logging.getLogger(__name__)

ONC_DP_URL = "https://data.oceannetworks.ca/api/dataProductDelivery"
ONC_PRODUCTS_URL = "https://data.oceannetworks.ca/api/dataProducts"

# Depth-binned ADCP time series, by instrument vendor. Both products carry the same
# variables (`meanBackscatter(depth, time)` in dB, a `depth` coordinate in metres),
# so one parser handles both — only the product code differs.
#   RADCPTS — Teledyne RDI (4 beams)
#   NTS     — Nortek        (3 beams)
# Preference order is irrelevant; a device offers exactly one of them.
ADCP_PRODUCT_CODES = ("RADCPTS", "NTS")

# `searchHdrStatus` values. ONC does not document the full set; anything not listed
# here is treated as "still working" and we let the timeout decide, rather than
# guessing a failure and discarding a product that was merely slow.
_STATUS_DONE = "COMPLETED"
_STATUS_FAILED = frozenset({"ERROR", "FAILED", "CANCELLED"})


def adcp_device_category_code(device_category: str) -> str | None:
    """Map our stored long `device_category` to ONC's frequency-specific code.

    `'Acoustic Doppler Current Profiler 75 kHz'` → `'ADCP75KHZ'`.

    Returns None when the string is not a Doppler profiler at all. NOTE the stored
    category contains the words "Current Profiler", so a `LIKE '%CURRENT%'` filter
    also matches plain `'Current Meter'` — match on "Doppler", never on "Current".
    """
    if "doppler" not in device_category.lower():
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(MHz|kHz)", device_category, re.IGNORECASE)
    if not m:
        return None
    num = m.group(1)
    if "." in num:
        num = num.rstrip("0").rstrip(".")
    return f"ADCP{num}{m.group(2).upper()}"


class NoProductFile(Exception):
    """The run completed but produced no downloadable file — no data in the window.

    Distinct from a failure: the request was well-formed and ONC answered honestly.
    """


def pick_product_code(entries: list[dict], extension: str = "nc") -> str | None:
    """Choose the ADCP time-series product a device actually offers.

    Do NOT infer this from the instrument frequency. `dataProducts` is authoritative:
    BACAX/ADCP2MHZ and HRBIP/ADCP400KHZ are Nortek and offer only `NTS`, while
    RCNE5/ADCP75KHZ is RDI and offers only `RADCPTS`. Ordering RADCPTS from a Nortek
    device returns HTTP 400 errorCode 127 ("deviceCategoryCode does not have
    corresponding dataProductCode and extension").
    """
    offered = {
        (e.get("dataProductCode"), e.get("extension"))
        for e in entries
        if isinstance(e, dict)
    }
    for code in ADCP_PRODUCT_CODES:
        if (code, extension) in offered:
            return code
    return None


async def resolve_adcp_product(
    client: httpx.AsyncClient,
    token: str,
    location_code: str,
    device_category_code: str,
    *,
    extension: str = "nc",
) -> str | None:
    """Ask ONC which ADCP time-series product this device publishes."""
    r = await client.get(
        ONC_PRODUCTS_URL,
        params={
            "locationCode": location_code,
            "deviceCategoryCode": device_category_code,
            "token": token,
        },
        timeout=60.0,
    )
    r.raise_for_status()
    body = r.json()
    if not isinstance(body, list):
        return None
    return pick_product_code(body, extension)


async def _get(client: httpx.AsyncClient, params: dict, timeout: float = 90.0) -> httpx.Response:
    return await client.get(ONC_DP_URL, params=params, timeout=timeout)


async def order_product(
    client: httpx.AsyncClient,
    token: str,
    *,
    location_code: str,
    device_category_code: str,
    data_product_code: str,
    extension: str,
    date_from: str,
    date_to: str,
    extra: dict | None = None,
) -> int:
    """`request` then `run`. Returns dpRunId."""
    params = {
        "method": "request",
        "token": token,
        "locationCode": location_code,
        "deviceCategoryCode": device_category_code,
        "dataProductCode": data_product_code,
        "extension": extension,
        "dateFrom": date_from,
        "dateTo": date_to,
        **(extra or {}),
    }
    r = await _get(client, params)
    r.raise_for_status()
    body = r.json()
    if "dpRequestId" not in body:
        raise RuntimeError(f"{location_code}: request rejected: {body.get('errors') or body}")

    r = await _get(client, {"method": "run", "token": token, "dpRequestId": body["dpRequestId"]})
    r.raise_for_status()
    runs = r.json()
    if not isinstance(runs, list) or not runs:
        raise RuntimeError(f"{location_code}: run returned {runs!r}")
    return int(runs[0]["dpRunId"])


async def wait_for_product(
    client: httpx.AsyncClient,
    token: str,
    dp_run_id: int,
    *,
    timeout_s: float = 600.0,
    poll_s: float = 10.0,
) -> None:
    """Poll until the run completes.

    The status payload has NO `status` key — the field is `searchHdrStatus`. A poller
    that greps for `"status": "complete"` waits forever against a finished job.
    """
    waited = 0.0
    while waited < timeout_s:
        r = await _get(client, {"method": "status", "token": token, "dpRunId": dp_run_id}, timeout=60.0)
        r.raise_for_status()
        status = str(r.json().get("searchHdrStatus", "")).upper()
        if status == _STATUS_DONE:
            return
        if status in _STATUS_FAILED:
            raise RuntimeError(f"dpRunId {dp_run_id}: run {status}")
        await asyncio.sleep(poll_s)
        waited += poll_s
    raise TimeoutError(f"dpRunId {dp_run_id}: not complete after {timeout_s:.0f}s")


async def download_product(
    client: httpx.AsyncClient,
    token: str,
    dp_run_id: int,
    dest_path: str,
    *,
    index: int = 1,
    timeout_s: float = 300.0,
) -> str:
    """Download one produced file. 202 means "still generating" — retry, don't write it."""
    deadline = timeout_s
    while deadline > 0:
        r = await _get(
            client,
            {"method": "download", "token": token, "dpRunId": dp_run_id, "index": index},
            timeout=timeout_s,
        )
        if r.status_code == 202:
            await asyncio.sleep(5)
            deadline -= 5
            continue
        if r.status_code == 404:
            # Run completed, no file at this index: the instrument logged nothing in
            # the requested window. Not an error — don't let it inflate the failure count.
            raise NoProductFile(f"dpRunId {dp_run_id}: no file at index {index}")
        r.raise_for_status()
        with open(dest_path, "wb") as fh:
            fh.write(r.content)
        return dest_path
    raise TimeoutError(f"dpRunId {dp_run_id}: download still 202 after {timeout_s:.0f}s")
