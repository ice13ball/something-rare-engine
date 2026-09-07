# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Identify ourselves, and retry only what is worth retrying.

sio-bic returns HTTP 403 to a bare curl. Before assuming a deliberate block,
send an honest User-Agent naming the project and a contact — many WAFs reject
the default agent with no intent to block anyone. If 403 survives that, it IS a
block: set Blocked in the cadence registry and write to them. Do not escalate.
"""
from ingestion import USER_AGENT


def test_user_agent_identifies_the_project_and_a_contact():
    assert "AbyssalClaims" in USER_AGENT
    assert "something-rare.com" in USER_AGENT


def test_user_agent_does_not_impersonate_a_browser():
    """Being identifiable is a different act from circumventing a block."""
    for pretend in ("Mozilla", "Chrome", "Safari", "Gecko", "AppleWebKit"):
        assert pretend not in USER_AGENT


# ── NCEI retry: retry what is worth retrying, and do not sleep on the way out ─

import asyncio

import httpx
import pytest

from domains.land import density


class _FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"results": []}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=None, response=None)

    def json(self):
        return self._payload


class _ScriptedClient:
    """Replays a scripted sequence of responses/exceptions, counting calls."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def get(self, url, params=None):
        self.calls += 1
        item = self.script.pop(0) if self.script else self.script_default()
        if isinstance(item, Exception):
            raise item
        return item

    def script_default(self):
        return _FakeResponse(500)


@pytest.fixture
def no_real_sleep(monkeypatch):
    slept: list[float] = []

    async def _sleep(s):
        slept.append(s)

    monkeypatch.setattr(density.asyncio, "sleep", _sleep)
    return slept


@pytest.mark.asyncio
async def test_a_connection_error_is_retried_rather_than_given_zero_attempts(
    no_real_sleep,
):
    """`except Exception: break` gave transport failures NO retry at all.

    A 500 got three tries; a dropped connection — the more common failure on a
    VPS whose IPv6 route to NCEI is black-holed — got one. That is backwards:
    the 500 is the upstream's considered answer, the dropped connection is noise.
    """
    client = _ScriptedClient([
        httpx.ConnectError("connection reset"),
        httpx.ReadTimeout("timed out"),
        _FakeResponse(200, {"results": [{"filePath": "x"}]}),
    ])
    data = await density._fetch_ncei_year(client, 2011, {})
    assert client.calls == 3
    assert data == {"results": [{"filePath": "x"}]}


@pytest.mark.asyncio
async def test_no_sleep_after_the_final_failed_attempt(no_real_sleep):
    """The old loop slept 8s and then gave up — 8 wasted seconds per year, and
    `_NCEI_YEARS` has 21 of them: nearly three minutes of pure waiting per run."""
    client = _ScriptedClient([_FakeResponse(500)] * 3)
    data = await density._fetch_ncei_year(client, 2011, {})
    assert data is None
    assert len(no_real_sleep) == 2, (
        f"slept {len(no_real_sleep)} times for 3 attempts — the last one is waste"
    )


@pytest.mark.asyncio
async def test_a_4xx_is_not_retried(no_real_sleep):
    """A 4xx is OUR malformed request. Retrying burns their quota and our time."""
    client = _ScriptedClient([_FakeResponse(400)] * 3)
    data = await density._fetch_ncei_year(client, 2011, {})
    assert data is None
    assert client.calls == 1
    assert no_real_sleep == []


@pytest.mark.asyncio
async def test_a_first_attempt_success_does_not_sleep(no_real_sleep):
    client = _ScriptedClient([_FakeResponse(200, {"results": []})])
    assert await density._fetch_ncei_year(client, 2011, {}) == {"results": []}
    assert client.calls == 1
    assert no_real_sleep == []
