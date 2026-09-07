# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import asyncio

import httpx
import pytest

from backend.scripts.link_audit.fetch import classify, fetch_all
from backend.scripts.link_audit.models import FetchResult


def _r(status=200, final="https://x.org/", title=None, error=None, url="https://x.org/"):
    return FetchResult(url=url, status=status, final_url=final, title=title, error=error)


def test_200_same_url_is_ok():
    assert classify(_r()) == "OK"


def test_redirect_to_a_working_page_is_redirect_ok_not_a_defect():
    """GEBCO's BODC URLs 301 to CEDA by the publisher's own design."""
    res = _r(status=200, url="https://www.bodc.ac.uk/gebco/", final="https://data.ceda.ac.uk/gebco/")
    assert classify(res) == "REDIRECT_OK"


def test_403_is_blocked_not_dead():
    assert classify(_r(status=403)) == "BLOCKED"


def test_429_is_rate_limited():
    assert classify(_r(status=429)) == "RATE_LIMITED"


def test_5xx_is_blocked_not_dead():
    assert classify(_r(status=503)) == "BLOCKED"


def test_404_is_dead():
    assert classify(_r(status=404)) == "DEAD"


def test_network_error_is_blocked_not_dead():
    assert classify(_r(status=None, final=None, error="ConnectTimeout")) == "BLOCKED"


def test_200_with_soft_404_title_is_changed_meaning():
    assert classify(_r(title="404 Page Not Found")) == "CHANGED_MEANING"


def test_200_with_parked_domain_title_is_changed_meaning():
    assert classify(_r(title="This domain is for sale")) == "CHANGED_MEANING"


def test_legitimate_title_containing_the_digits_404_is_not_flagged():
    """A dataset page titled 'Station 404 CTD casts' is not a soft 404."""
    assert classify(_r(title="Station 404 CTD casts")) == "OK"


def test_fetch_all_uses_get_and_a_browser_user_agent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["ua"] = request.headers.get("user-agent", "")
        return httpx.Response(200, html="<html><title>Fine</title></html>")

    results = asyncio.run(
        fetch_all(["https://x.org/"], transport=httpx.MockTransport(handler)))
    assert seen["method"] == "GET"          # HEAD 405s on many gov endpoints
    assert "Mozilla" in seen["ua"]          # default agents get WAF-blocked
    assert results[0].status == 200
    assert results[0].title == "Fine"


def test_fetch_all_retries_once_on_503_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, html="<html><title>Up</title></html>")

    # Don't actually sleep between retries in tests.
    async def no_sleep(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    results = asyncio.run(
        fetch_all(["https://x.org/"], transport=httpx.MockTransport(handler)))
    assert calls["n"] == 2
    assert results[0].status == 200


def test_fetch_all_retries_once_on_exception_then_succeeds(monkeypatch):
    """Would fail against an implementation that gives up after a single
    transport exception (no retry loop / attempt-counting bug): calls["n"]
    would be 1 instead of 2, and status would never reach 200."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, html="<html><title>Up</title></html>")

    async def no_sleep(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    results = asyncio.run(
        fetch_all(["https://x.org/"], transport=httpx.MockTransport(handler)))
    assert calls["n"] == 2
    assert results[0].status == 200
    assert results[0].error is None


def test_fetch_all_gives_up_after_exception_on_both_attempts_is_blocked_not_dead(monkeypatch):
    """Would fail against an implementation that (a) retries more than once /
    hangs, (b) maps an unreachable host to DEAD instead of BLOCKED, or
    (c) leaves status/final_url as something other than None on total
    failure."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("boom")

    async def no_sleep(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    results = asyncio.run(
        fetch_all(["https://x.org/"], transport=httpx.MockTransport(handler)))
    assert calls["n"] == 2
    result = results[0]
    assert result.status is None
    assert result.final_url is None
    assert result.error is not None
    assert classify(result) == "BLOCKED"


def test_fetch_all_retries_once_on_503_on_both_attempts_is_blocked_not_dead(monkeypatch):
    """Would fail against an implementation that only retries once total
    across the whole run (rather than once per URL) or that maps a
    persistent 5xx to DEAD instead of BLOCKED."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    async def no_sleep(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    results = asyncio.run(
        fetch_all(["https://x.org/"], transport=httpx.MockTransport(handler)))
    assert calls["n"] == 2
    result = results[0]
    assert result.status == 503
    assert classify(result) == "BLOCKED"
