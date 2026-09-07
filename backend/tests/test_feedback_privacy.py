# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Privacy/security regression tests for backend/routers/feedback.py.

Covers two pre-publication defects:
  1. FEEDBACK_IP_SALT had a hard-coded fallback ("abyssal"), making every
     stored ip_hash brute-forceable across the whole IPv4 space once the
     source (and thus the fallback literal) is public.
  2. _post_discord() forwarded user-supplied text into a Discord message
     with no `allowed_mentions` guard, letting @everyone/@here/role pings
     reach the whole server.

These tests exercise the real code (`_compute_ip_hash`, `_post_discord`),
not a re-implementation of it.
"""

from __future__ import annotations

import hashlib

import pytest

from routers import feedback


# The literal that used to be the hard-coded salt fallback. Kept here as an
# explicit "known-bad" value the fix must never reproduce.
_OLD_HARDCODED_SALT = "abyssal"


def _old_vulnerable_hash(ip: str) -> str:
    """Reproduce the pre-fix hashing exactly, for the bound assertion."""
    return hashlib.sha256(f"{ip}{_OLD_HARDCODED_SALT}".encode()).hexdigest()[:32]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # Make sure no ambient FEEDBACK_IP_SALT from a real .env leaks into a test
    # that expects it to be unset.
    monkeypatch.delenv("FEEDBACK_IP_SALT", raising=False)
    yield


# ---------------------------------------------------------------------------
# Defect 1 — salt handling
# ---------------------------------------------------------------------------


def test_same_ip_same_salt_hashes_identically(monkeypatch):
    monkeypatch.setenv("FEEDBACK_IP_SALT", "test-salt-value")
    h1 = feedback._compute_ip_hash("1.2.3.4")
    h2 = feedback._compute_ip_hash("1.2.3.4")
    assert h1 is not None
    assert h1 == h2


def test_different_ips_same_salt_hash_differently(monkeypatch):
    monkeypatch.setenv("FEEDBACK_IP_SALT", "test-salt-value")
    h1 = feedback._compute_ip_hash("1.2.3.4")
    h2 = feedback._compute_ip_hash("5.6.7.8")
    assert h1 != h2


def test_salt_unset_does_not_reproduce_old_hardcoded_hash(monkeypatch, caplog):
    # Bound assertion: this is exactly what would have been returned by the
    # pre-fix code (`os.environ.get("FEEDBACK_IP_SALT", "abyssal")` +
    # sha256 concatenation) for this IP. A test that only checks "returns
    # something" would have passed before the fix too.
    forbidden = _old_vulnerable_hash("1.2.3.4")

    result = feedback._compute_ip_hash("1.2.3.4")

    assert result != forbidden
    # Deliberate, documented behaviour: no salt -> no hash, not a fallback hash.
    assert result is None


def test_salt_unset_logs_a_warning(monkeypatch, caplog):
    with caplog.at_level("WARNING", logger=feedback.log.name):
        feedback._compute_ip_hash("1.2.3.4")
    assert any("FEEDBACK_IP_SALT" in rec.message for rec in caplog.records)


def test_salt_set_uses_hmac_not_bare_concatenation(monkeypatch):
    # HMAC-SHA256 truncated to 32 hex chars must differ from the naive
    # sha256(ip + salt) construction, even for a matching salt/ip pair.
    monkeypatch.setenv("FEEDBACK_IP_SALT", _OLD_HARDCODED_SALT)
    naive = hashlib.sha256(f"1.2.3.4{_OLD_HARDCODED_SALT}".encode()).hexdigest()[:32]
    result = feedback._compute_ip_hash("1.2.3.4")
    assert result != naive


# ---------------------------------------------------------------------------
# Defect 2 — Discord allowed_mentions
# ---------------------------------------------------------------------------


class _FakeResponse:
    status = 200


class _FakeClientSession:
    """Stub for aiohttp.ClientSession that records post() calls instead of
    making a real network call."""

    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, timeout=None):
        _FakeClientSession.calls.append({"url": url, "json": json, "timeout": timeout})
        return _FakeResponse()


@pytest.fixture
def fake_discord_session(monkeypatch):
    _FakeClientSession.calls = []
    monkeypatch.setattr(feedback.aiohttp, "ClientSession", _FakeClientSession)
    return _FakeClientSession


@pytest.mark.asyncio
async def test_post_discord_sets_allowed_mentions_empty_parse(fake_discord_session):
    body = feedback.FeedbackBody(
        kind="bug",
        message="@everyone please look at this",
        dwell_ms=5000,
    )

    await feedback._post_discord("https://discord.example/webhook", body, row_id=1)

    assert len(fake_discord_session.calls) == 1
    payload = fake_discord_session.calls[0]["json"]
    assert "allowed_mentions" in payload
    assert payload["allowed_mentions"] == {"parse": []}
    # The mention text itself is preserved verbatim (rendered inert by
    # Discord's allowed_mentions, not by our own sanitisation/escaping).
    assert "@everyone" in payload["content"]
