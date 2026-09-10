# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The login handshake is the first call of the MEMENTO sync — and it was bare.

Observed live on production 2026-09-10, forcing a re-sync so a new column could
be filled:

    requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='portal.geomar.de',
    port=443): Read timed out. (read timeout=60)

Credentials were valid and set. One transient timeout on the handshake
discarded the whole ingest — 218,271 samples not refreshed — which is check
25e, the same shape as the ArgoVis vocabulary call that aborted an Argo run on
2026-09-09.

⛔ A REJECTED credential must NOT be retried. Re-posting a password the server
has already refused is how an account gets locked, so only transport failures
earn another attempt. These tests pin both halves, because a retry loop that
cannot tell them apart is worse than no retry at all.
"""
import pytest
import requests

from ingestion import memento_ingest as mi


#: One shared script and one shared attempt-log, at module level. An earlier
#: version kept them in a fixture closure and the session ended up popping from
#: a different list than the test filled — green once, then IndexError. Module
#: state has one owner and cannot drift.
_SCRIPT: list = []
_ATTEMPTS: list = []


class _Session:
    """One scripted attempt: either raises on POST, or returns a status + cookies."""

    def __init__(self):
        self.headers = {}
        self.cookies = {}
        _ATTEMPTS.append(self)

    def get(self, url, timeout=None):
        class _R:
            text = ""
        return _R()

    def post(self, url, data=None, timeout=None, allow_redirects=None):
        assert _SCRIPT, "fixture problem: more POSTs than the script provides"
        item = _SCRIPT.pop(0)
        if isinstance(item, Exception):
            raise item
        status, ok = item
        if ok:
            self.cookies["JSESSIONID"] = "abc"

        class _R:
            status_code = status
        return _R()


@pytest.fixture(autouse=True)
def _fake_requests(monkeypatch):
    import sys
    _SCRIPT.clear()
    _ATTEMPTS.clear()
    fake = type("R", (), {
        "Session": staticmethod(_Session),
        "exceptions": requests.exceptions,
    })
    monkeypatch.setitem(sys.modules, "requests", fake)


def _login(script, attempts=3):
    _SCRIPT[:] = script
    _ATTEMPTS.clear()
    return mi.login_session("a@b.c", "pw", attempts=attempts, sleep=lambda _s: None)


def test_a_read_timeout_is_retried():
    """The exact failure seen on production."""
    s = _login([requests.exceptions.ReadTimeout("read timed out"), (302, True)])
    assert "JSESSIONID" in s.cookies
    assert len(_ATTEMPTS) == 2, (
        f"{len(_ATTEMPTS)} attempt(s) — the timeout was not retried, so one "
        "slow response still discards the whole ingest"
    )


def test_it_gives_up_and_raises_the_transport_error():
    with pytest.raises(requests.exceptions.RequestException):
        _login([requests.exceptions.ConnectTimeout("nope")] * 3)
    assert len(_ATTEMPTS) == 3


def test_a_refused_credential_is_NOT_retried():
    """⛔ The half that matters more. Re-posting a refused password locks accounts."""
    with pytest.raises(RuntimeError, match="check credentials"):
        _login([(401, False), (401, False), (401, False)])
    assert len(_ATTEMPTS) == 1, (
        f"the login form was posted {len(_ATTEMPTS)} times with a password "
        "the server had already refused"
    )


def test_a_successful_first_attempt_does_not_retry():
    s = _login([(302, True)])
    assert "JSESSIONID" in s.cookies
    assert len(_ATTEMPTS) == 1
