# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""One shared GET-with-retry for the ingest modules.

⛔ `grep -l 'retry\\|backoff\\|attempt' backend/ingestion/acoustic_*.py` returned
NOTHING across thirteen modules on 2026-09-10 — fourteen HTTP call sites, every
one a single unprotected request to a government or university portal. The
acoustic station sync runs weekly and catches per-source failures, so one
transient 502 did not crash anything: it silently left that source's rows a
week stale. SAMBAH alone is 298 of 641 stations.

This is the same helper that was written inline for `domains/offshore.py`
(check 25e), lifted so the next ingest does not write a third copy.

Semantics, and each one is deliberate:

  * 5xx and transport errors are retried, with a growing pause between tries.
  * A 4xx is NOT retried and raises immediately. A 404 or 400 is the server
    saying the resource moved or the query is wrong; repeating it cannot change
    the answer and only hammers a public registry.
  * Exhaustion RAISES the last error rather than returning None, because
    "this source is unreachable" and "this source has nothing" must never share
    a code path — the caller decides, and it can only decide if it is told.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

DEFAULT_ATTEMPTS = 3


async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    label: str = "",
    attempts: int = DEFAULT_ATTEMPTS,
    **kwargs: Any,
) -> httpx.Response:
    """One GET, retried on transport failure and on 5xx. See module docstring."""
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            resp = await client.get(url, **kwargs)
            if resp.status_code < 500:
                resp.raise_for_status()      # 4xx raises here and is not retried
                return resp
            last = httpx.HTTPStatusError(
                f"HTTP {resp.status_code}", request=resp.request, response=resp)
            log.warning("ingest: %s -> HTTP %s (attempt %d/%d)",
                        label or url, resp.status_code, attempt + 1, attempts)
        except httpx.HTTPStatusError:
            raise                            # deliberate: see above
        except Exception as exc:
            last = exc
            log.warning("ingest: %s -> %s (attempt %d/%d)",
                        label or url, type(exc).__name__, attempt + 1, attempts)
        if attempt + 1 < attempts:
            await asyncio.sleep(2 * (attempt + 1))
    raise last if last else RuntimeError(f"ingest: {label or url} failed")
