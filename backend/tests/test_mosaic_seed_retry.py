# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The first call of a sync must be as protected as the two hundred after it.

`sync_mosaic` opened with a bare `client.get(_MOSAIC_GEO_URL)` — the request
that produces every core — while each per-tile sample request below it retried
three times with backoff. One transient failure on the seed aborted the whole
run with zero cores written, and the log said only that the sync had failed.

This is the same shape as the ArgoVis defect measured on 2026-09-09: a single
429 on `/argo/vocabulary`, the opening call, threw away a run whose every
later call was retried five times. Check 25e of abyssal-new-layer-check exists
because of it.
"""
import asyncio

import pytest

from domains import geochem


class _Resp:
    def __init__(self, code, body=None):
        self.status_code = code
        self._body = body if body is not None else []

    def json(self):
        return self._body


class _Client:
    """Answers with the queued responses, raising anything that is an Exception."""
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def get(self, url, params=None, timeout=None):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    """Otherwise every retry test pays the real 2s/4s/6s backoff."""
    async def instant(_s):
        return None
    monkeypatch.setattr(geochem.asyncio, "sleep", instant)


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_a_transient_failure_on_the_seed_is_retried_not_fatal():
    client = _Client([RuntimeError("connection reset"), _Resp(200, [{"core_id": 1}])])
    got = _run(geochem._mosaic_get_with_retry(client, "http://x", label="seed"))
    assert got == [{"core_id": 1}], (
        "the seed request gave up on the first transient failure — the whole "
        "sync writes zero cores when that happens"
    )
    assert client.calls == 2, f"{client.calls} attempt(s); the retry did not happen"


def test_a_429_on_the_seed_is_retried_too():
    """The ArgoVis case verbatim: rate-limited, not broken."""
    client = _Client([_Resp(429), _Resp(429), _Resp(200, [{"core_id": 7}])])
    got = _run(geochem._mosaic_get_with_retry(client, "http://x", label="seed"))
    assert got == [{"core_id": 7}]
    assert client.calls == 3


def test_it_gives_up_rather_than_looping_forever():
    """⛔ A retry that never stops is an outage we inflicted on the source."""
    client = _Client([RuntimeError("boom")] * 3)
    with pytest.raises(RuntimeError):
        _run(geochem._mosaic_get_with_retry(client, "http://x", label="seed", retries=3))
    assert client.calls == 3, f"{client.calls} attempts for retries=3"


def test_a_seed_failure_raises_instead_of_returning_an_empty_list():
    """⛔ "Missing" and "broken" must not share a code path.

    Returning [] would let the sync proceed to write nothing and report
    success — the source having no cores and the source being unreachable
    would look identical in sync_log.
    """
    client = _Client([RuntimeError("boom")] * 3)
    with pytest.raises(RuntimeError):
        _run(geochem._mosaic_get_with_retry(client, "http://x", label="seed", retries=3))


def test_the_seed_call_site_actually_uses_the_helper():
    """⛔ The four tests above bind the HELPER, not its use.

    Caught by sabotage on 2026-09-10: reverting `sync_mosaic` to the bare
    `client.get(_MOSAIC_GEO_URL, timeout=180)` left all four of them green.
    A helper nobody calls protects nothing, so the call site needs its own
    guard — a structural one, because driving `sync_mosaic` end to end needs
    a live pool and would test the database rather than this decision.
    """
    import ast
    import inspect

    src = inspect.getsource(geochem)
    tree = ast.parse(src)

    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "sync_mosaic")

    bare = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute) and n.func.attr == "get"
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "client"
    ]
    assert not bare, (
        "sync_mosaic calls client.get directly; every request it makes must go "
        "through _mosaic_get_with_retry, or the first failure of the run "
        "discards it with zero cores written"
    )

    helper_calls = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "_mosaic_get_with_retry"
    ]
    assert helper_calls, (
        "fixture problem: sync_mosaic makes no retried request at all — the "
        "AST walk found nothing, so the assertion above proved nothing"
    )
