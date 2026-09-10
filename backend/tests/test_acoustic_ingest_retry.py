# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Every acoustic ingest fetch retries a transient failure. All fourteen.

`grep -l 'retry\\|backoff\\|attempt' backend/ingestion/acoustic_*.py` returned
nothing on 2026-09-10 across thirteen modules and fourteen HTTP call sites,
each a single unprotected request to a government or university portal.

The weekly station sync catches per-source failures and continues, and the
upsert never deletes — so one transient 502 did not crash anything and did not
lose a row. It silently left that source a week stale. SAMBAH alone is 298 of
641 stations, and nothing in sync_log distinguishes "fetched and unchanged"
from "never reached".

⛔ Both halves are guarded. Testing the helper alone is how four green MOSAIC
tests survived sync_mosaic being reverted to a bare client.get, how the
offshore retry landed on 4 of 7 call sites, and how the currents float grid
was written by a function nobody called with it — three times in one week.
"""
import ast
import asyncio
import pathlib

import httpx
import pytest

INGEST = pathlib.Path(__file__).resolve().parents[1] / "ingestion"
MODULES = sorted(INGEST.glob("acoustic_*_ingest.py"))


# ── The call sites ──────────────────────────────────────────────────────────

def _bare_gets(path: pathlib.Path) -> list[int]:
    """Line numbers of `await <something>.get(...)` that bypass the helper."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if (isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "get"
                and isinstance(call.func.value, ast.Name)):
            out.append(node.lineno)
    return out


def test_the_fixture_found_the_modules_and_the_helper_is_really_used():
    assert len(MODULES) >= 10, f"fixture problem: found {len(MODULES)} acoustic ingests"
    users = [m.name for m in MODULES
             if "get_with_retry" in m.read_text(encoding="utf-8")]
    assert len(users) >= 5, (
        f"fixture problem: only {users} reference the helper — if none did, the "
        "call-site test below would pass on a file with no fetches at all"
    )


def test_no_acoustic_ingest_fetches_without_a_retry():
    offenders = {m.name: lines for m in MODULES if (lines := _bare_gets(m))}
    assert not offenders, (
        f"bare client.get in acoustic ingests: {offenders}. One transient 502 "
        "leaves that source's stations a week stale with nothing to show for it."
    )


def test_the_helper_is_imported_at_module_level_where_it_is_used():
    # An import buried inside a function still works, but hides the dependency
    # from exactly the grep that found this gap in the first place.
    bad = []
    for m in MODULES:
        src = m.read_text(encoding="utf-8")
        if "get_with_retry" not in src:
            continue
        tree = ast.parse(src)
        top = {a.name for n in tree.body if isinstance(n, ast.ImportFrom)
               for a in n.names}
        if "get_with_retry" not in top:
            bad.append(m.name)
    assert not bad, f"get_with_retry imported below module level in: {bad}"


# ── The helper ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    """The helper's backoff is 2s then 4s. Real waits would cost 12s a run."""
    import ingestion.http_retry as hr
    slept: list[float] = []

    async def fake(sec):
        slept.append(sec)

    monkeypatch.setattr(hr.asyncio, "sleep", fake)
    return slept


class _Client:
    """Answers a scripted list of outcomes, counting the attempts."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    async def get(self, url, **kw):
        self.calls += 1
        item = self.script.pop(0) if self.script else self.script
        if isinstance(item, Exception):
            raise item
        req = httpx.Request("GET", url)
        return httpx.Response(item, request=req)


@pytest.mark.asyncio
async def test_a_transient_failure_is_retried_and_then_succeeds():
    from ingestion.http_retry import get_with_retry
    c = _Client([httpx.ConnectError("boom"), 503, 200])
    resp = await get_with_retry(c, "https://example.invalid/x", label="t", attempts=3)
    assert resp.status_code == 200
    assert c.calls == 3, f"gave up after {c.calls} attempt(s)"


@pytest.mark.asyncio
async def test_a_4xx_is_not_retried_because_repeating_it_cannot_help():
    from ingestion.http_retry import get_with_retry
    c = _Client([404, 200])
    with pytest.raises(httpx.HTTPStatusError):
        await get_with_retry(c, "https://example.invalid/x", label="t", attempts=3)
    assert c.calls == 1, (
        f"a 404 was requested {c.calls} times — the resource moved, and "
        "hammering a public registry does not move it back"
    )


@pytest.mark.asyncio
async def test_exhaustion_raises_rather_than_returning_nothing():
    # ⛔ Returning None here would put "unreachable" and "has nothing" back on
    # one code path, which is the confusion this whole audit keeps untangling.
    from ingestion.http_retry import get_with_retry
    c = _Client([500, 500, 500])
    with pytest.raises(Exception) as exc:
        await get_with_retry(c, "https://example.invalid/x", label="t", attempts=3)
    assert c.calls == 3
    assert exc.value is not None


@pytest.mark.asyncio
async def test_it_passes_the_caller_s_params_and_headers_through():
    # SAMBAH authenticates with a header; a helper that swallowed kwargs would
    # turn every one of its fetches into an anonymous 401.
    from ingestion.http_retry import get_with_retry
    seen = {}

    class _Spy(_Client):
        async def get(self, url, **kw):
            seen.update(kw)
            return await super().get(url, **kw)

    c = _Spy([200])
    await get_with_retry(c, "https://example.invalid/x",
                         params={"a": "1"}, headers={"Authorization": "Bearer x"},
                         label="t")
    assert seen.get("params") == {"a": "1"}
    assert seen.get("headers", {}).get("Authorization") == "Bearer x"


@pytest.mark.asyncio
async def test_the_default_attempt_count_is_more_than_one():
    # ⚠️ Every test above passes attempts=3 explicitly, so lowering
    # DEFAULT_ATTEMPTS to 1 left all of them green — and DEFAULT_ATTEMPTS is
    # what all fourteen real call sites use. Call it the way they call it.
    from ingestion.http_retry import get_with_retry
    c = _Client([httpx.ConnectError("boom"), 200])
    resp = await get_with_retry(c, "https://example.invalid/x", label="t")
    assert resp.status_code == 200, "the default gave up after one attempt"
    assert c.calls == 2


@pytest.mark.asyncio
async def test_it_waits_longer_between_each_attempt(no_real_sleeping):
    # A retry with no pause is three requests in one millisecond, which is what
    # a struggling registry least needs.
    from ingestion.http_retry import get_with_retry
    c = _Client([500, 500, 200])
    await get_with_retry(c, "https://example.invalid/x", label="t", attempts=3)
    assert len(no_real_sleeping) == 2, f"paused {len(no_real_sleeping)} time(s)"
    assert no_real_sleeping[1] > no_real_sleeping[0], (
        f"backoff did not grow: {no_real_sleeping}"
    )


@pytest.mark.asyncio
async def test_a_success_first_time_waits_for_nothing(no_real_sleeping):
    from ingestion.http_retry import get_with_retry
    c = _Client([200])
    await get_with_retry(c, "https://example.invalid/x", label="t")
    assert no_real_sleeping == [], "the happy path paused before returning"
