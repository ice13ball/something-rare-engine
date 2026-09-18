# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A day with no floats in it is an answer, not an outage.

ArgoVis answers **HTTP 404 with a literal empty JSON array** for a time window
it holds nothing for. Verified live 2026-09-18, one day each:

    1997-01-15  → 404, body `[]`
    1997-07-28  → 200, profiles          ← the feed's first day
    1997-08-15  → 200, profiles
    1999-01-02  → 200, profiles

`raise_for_status()` turned that into an exception, and the walk treats an
exception as a failed chunk: the cursor must not advance, so the whole pass
stops. Measured the same day: a bounded walk from 1997-01-01 died on its FIRST
request and returned `months_done=0, stalled=True,
failed_chunk='1997-01-01..1997-02-01'`. The 940 profiles ArgoVis holds for
1997-1998 stayed unreachable because January 1997 is empty.

⚠️ The same trap applies anywhere in the record, not just at the start: one
empty day in the middle of a month ends that pass too.

⛔ The tolerance is deliberately narrow — an empty LIST only. A 404 carrying a
message, or a body that is not a list, stays an error. Otherwise a wrong
endpoint would read as an ocean with no floats in it, forever, in silence.
"""
import logging

import httpx
import pytest

from domains import sensors


def _resp(status: int, body: str, *, json_ct: bool = True) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        content=body.encode(),
        headers={"content-type": "application/json" if json_ct else "text/html"},
        request=httpx.Request("GET", "https://argovis-api.colorado.edu/argo"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# The discriminator, on its own.
# ─────────────────────────────────────────────────────────────────────────────

def test_an_empty_list_body_is_recognised_as_an_empty_window():
    assert sensors._is_empty_argo_window(_resp(404, "[\n\n]")) is True
    assert sensors._is_empty_argo_window(_resp(404, "[]")) is True


@pytest.mark.parametrize("body", [
    '{"message": "route not found"}',          # an object, not a list
    '[{"_id": "13858_001"}]',                  # a NON-empty list
    "Not Found",                               # not JSON at all
    "",                                        # empty body
])
def test_anything_else_is_still_a_failure(body):
    assert sensors._is_empty_argo_window(_resp(404, body)) is False, (
        f"{body!r} was accepted as 'no data' — a real 404 would go silent")


# ─────────────────────────────────────────────────────────────────────────────
# The fetch path, which is where the stall happened.
# ─────────────────────────────────────────────────────────────────────────────

class _Client:
    """Minimal stand-in for httpx.AsyncClient.get."""

    def __init__(self, response):
        self._response = response
        self.calls = 0

    async def get(self, url, params=None):
        self.calls += 1
        return self._response


async def test_an_empty_day_returns_no_profiles_and_does_not_raise(caplog):
    from datetime import datetime, timezone

    client = _Client(_resp(404, "[\n\n]"))
    start = datetime(1997, 1, 15, tzinfo=timezone.utc)
    end = datetime(1997, 1, 16, tzinfo=timezone.utc)

    with caplog.at_level(logging.INFO):
        profiles = await sensors._fetch_argo_window(client, start, end, None)

    assert profiles == []
    assert any("1997-01-15" in r.getMessage() and "no profiles" in r.getMessage()
               for r in caplog.records), (
        "an empty day passed without a word — 'we asked and there was nothing' "
        "must be distinguishable from 'we never asked'")


async def test_a_real_404_still_raises():
    from datetime import datetime, timezone

    client = _Client(_resp(404, '{"message": "route not found"}'))
    with pytest.raises(httpx.HTTPStatusError):
        await sensors._fetch_argo_window(
            client,
            datetime(2020, 1, 1, tzinfo=timezone.utc),
            datetime(2020, 1, 2, tzinfo=timezone.utc),
            None,
        )


async def test_a_day_with_profiles_is_unaffected():
    from datetime import datetime, timezone

    body = '[{"_id": "13858_001"}, {"_id": "13858_001"}, {"_id": "13858_002"}]'
    client = _Client(_resp(200, body))
    profiles = await sensors._fetch_argo_window(
        client,
        datetime(1997, 7, 28, tzinfo=timezone.utc),
        datetime(1997, 7, 29, tzinfo=timezone.utc),
        None,
    )
    # dedupe by _id survives the change
    assert [p["_id"] for p in profiles] == ["13858_001", "13858_002"]


async def test_a_500_is_not_swallowed_even_with_an_empty_list_body():
    """⛔ Only 404 means "nothing here". A 5xx with the same body is an outage
    and must reach the retry/failure path."""
    from datetime import datetime, timezone

    client = _Client(_resp(500, "[]"))
    with pytest.raises(httpx.HTTPStatusError):
        await sensors._fetch_argo_window(
            client,
            datetime(2020, 1, 1, tzinfo=timezone.utc),
            datetime(2020, 1, 2, tzinfo=timezone.utc),
            None,
        )
