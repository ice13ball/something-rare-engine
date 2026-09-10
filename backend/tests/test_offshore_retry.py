# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""offshore.py had no retry at all — 26 syncs, all against public registries.

`grep -cE 'retry|backoff|tenacity' backend/domains/offshore.py` returned ZERO
on 2026-09-10, in a file holding 26 sync functions that each talk to a
government ArcGIS or WFS endpoint. A single transient failure on an opening
fetch aborted that source's whole sync.

Check 25e, and the fourth instance of the same shape found in one week: the
ArgoVis vocabulary call, the MOSAIC seed fetch, the MEMENTO login, and this.

⛔ The asymmetry is the part worth guarding. A 4xx must NOT be retried — a 404
or a 400 is the registry telling us the layer moved or the query is wrong, and
repeating it cannot change the answer while it does hammer a public service.
A retry loop that cannot tell a timeout from a rejection is worse than none.
"""
import asyncio

import httpx
import pytest

from domains import offshore


class _Resp:
    def __init__(self, code, body=None):
        self.status_code = code
        self._body = body if body is not None else {"features": []}
        self.request = httpx.Request("GET", "http://x")

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=self.request, response=None)


class _Client:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def get(self, url, params=None):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    async def instant(_s):
        return None
    monkeypatch.setattr(offshore.asyncio, "sleep", instant)


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_a_transient_failure_is_retried():
    c = _Client([httpx.ConnectTimeout("nope"), _Resp(200, {"features": [1]})])
    r = _run(offshore._get_with_retry(c, "http://x", label="t"))
    assert r.json() == {"features": [1]}
    assert c.calls == 2, f"{c.calls} attempt(s) — the transient failure was not retried"


def test_a_500_is_retried():
    c = _Client([_Resp(500), _Resp(503), _Resp(200, {"features": [2]})])
    r = _run(offshore._get_with_retry(c, "http://x", label="t"))
    assert r.json() == {"features": [2]}
    assert c.calls == 3


def test_a_404_is_NOT_retried():
    """⛔ The half that matters. Repeating a 404 cannot change the answer."""
    c = _Client([_Resp(404), _Resp(404), _Resp(404)])
    with pytest.raises(httpx.HTTPStatusError):
        _run(offshore._get_with_retry(c, "http://x", label="t"))
    assert c.calls == 1, (
        f"a 404 was requested {c.calls} times; that is hammering a public "
        "registry with a question it has already answered"
    )


def test_it_gives_up_and_raises_rather_than_returning_empty():
    """⛔ "Unreachable" and "has nothing" must not share a code path — returning
    an empty response would let the sync write nothing and report success."""
    c = _Client([httpx.ConnectTimeout("nope")] * 3)
    with pytest.raises(Exception):
        _run(offshore._get_with_retry(c, "http://x", label="t", attempts=3))
    assert c.calls == 3


def test_a_first_attempt_that_works_does_not_retry():
    c = _Client([_Resp(200, {"features": [3]})])
    _run(offshore._get_with_retry(c, "http://x", label="t"))
    assert c.calls == 1


def test_the_opening_fetches_actually_use_the_helper():
    """⛔ A helper nobody calls protects nothing. Caught this way on MOSAIC
    earlier today: four tests of the helper stayed green while the call site
    was reverted to a bare client.get."""
    import inspect
    import re
    src = inspect.getsource(offshore)
    body = src.split("async def _get_with_retry", 1)[1]
    body = body.split('raise last if last else', 1)[1]   # everything AFTER the helper
    bare = re.findall(r"^\s*r = await client\.get\(", body, re.M)
    assert not bare, (
        f"{len(bare)} opening fetch(es) still call client.get directly; each is "
        "a whole source's sync discarded by one transient failure"
    )
    assert "_get_with_retry(client," in body, (
        "fixture problem: no call site uses the helper at all, so the "
        "assertion above proved nothing"
    )
