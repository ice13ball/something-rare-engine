# SPDX-License-Identifier: AGPL-3.0-or-later
"""The leak this closes was real: production journald carried the ONC token on
every request, because httpx logs the full request URL at INFO and the token is a
query parameter. These tests EXECUTE the filter against records shaped exactly the
way httpx and our own FIRMS call produce them."""
import importlib
import logging

import pytest

import log_redaction


def _strip_installed_filters():
    """⚠️ `importlib.reload` makes a NEW class object, so install()'s isinstance guard
    stops recognising the filter a previous test left behind. Without this, filters
    pile up on the root logger and a later test can pass on a stale module's secret
    set — green for the wrong reason."""
    root = logging.getLogger()
    for target in (root, *root.handlers):
        target.filters = [f for f in target.filters
                          if type(f).__name__ != "SecretRedactingFilter"]


@pytest.fixture(autouse=True)
def _clean_root_logger():
    _strip_installed_filters()
    yield
    _strip_installed_filters()


@pytest.fixture
def redactor(monkeypatch):
    """Install with a known, fake secret set. ⛔ Never reads the developer's real .env.

    ⚠️ Every value here is written so a secret scanner can tell at a glance that it
    is not one. The first version used a 32-character hex string for the FIRMS key —
    which is exactly what a real key looks like — and gitleaks' generic-api-key rule
    stopped the public-mirror export dead. That was the gate working. ⛔ Do not answer
    a finding like that by allowlisting the rule: a scanner taught to ignore
    key-shaped strings in tests will ignore the real one the day it lands in a test.
    Make the fixture unmistakable instead.
    """
    monkeypatch.setenv("ONC_TOKEN", "00000000-fake-4000-9000-000000000000")
    monkeypatch.setenv("FIRMS_MAP_KEY", "not-a-real-firms-key-PLACEHOLDER")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:not-a-real-password-PLACEHOLDER@localhost/abyssal")
    for name in ("OPENAQ_API_KEY", "ABYSSAL_API_KEY", "CMEMS_PASSWORD",
                 "ADMIN_DASHBOARD_TOKEN", "ADMIN_BOOTSTRAP_PASSWORD",
                 "STRIPE_SECRET_KEY", "TELEGRAM_BOT_TOKEN", "MIRROR_PUSH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    importlib.reload(log_redaction)
    count = log_redaction.install()
    assert count == 3, f"expected 3 secrets, got {count}"
    return log_redaction


def _render(record: logging.LogRecord) -> str:
    """Apply the installed filter the way a handler would, then format."""
    for f in logging.getLogger().filters:
        f.filter(record)
    return record.getMessage()


def test_onc_token_in_a_query_string_is_gone(redactor):
    """The exact shape found in the journal on 2026-09-08."""
    url = ("https://data.oceannetworks.ca/api/scalardata/location?method=getByLocation"
           "&locationCode=SEIR&deviceCategoryCode=CTD&rowLimit=1"
           "&token=00000000-fake-4000-9000-000000000000")
    rec = logging.LogRecord("httpx", logging.INFO, __file__, 1,
                            'HTTP Request: %s %s "%s %d %s"',
                            ("GET", url, "HTTP/1.1", 200, "OK"), None)
    out = _render(rec)
    assert "00000000-fake" not in out
    assert log_redaction.PLACEHOLDER in out
    # The rest of the line must survive — a redactor that eats the whole URL
    # destroys the diagnostic value the log was there for.
    assert "locationCode=SEIR" in out
    assert "HTTP/1.1 200 OK" in out


def test_firms_key_in_a_PATH_segment_is_gone(redactor):
    """⛔ The case a name-based rule can never catch: the key has no parameter name.

    We build https://…/api/area/csv/{FIRMS_MAP_KEY}/VIIRS/world/3 — the credential is
    a bare path segment, indistinguishable from a sensor code. Only value-matching
    finds it."""
    url = ("https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
           "not-a-real-firms-key-PLACEHOLDER/VIIRS_SNPP_NRT/world/3")
    rec = logging.LogRecord("httpx", logging.INFO, __file__, 1,
                            "HTTP Request: %s %s", ("GET", url), None)
    out = _render(rec)
    assert "not-a-real-firms-key" not in out
    assert log_redaction.PLACEHOLDER in out
    assert "VIIRS_SNPP_NRT/world/3" in out


def test_database_password_inside_a_dsn_is_gone(redactor):
    rec = logging.LogRecord("db", logging.ERROR, __file__, 1,
                            "connect failed: %s",
                            ("postgresql://user:not-a-real-password-PLACEHOLDER@localhost/abyssal",), None)
    out = _render(rec)
    assert "not-a-real-password" not in out
    assert "postgresql://user:" in out


def test_an_unknown_key_is_still_caught_by_name(redactor):
    """Rule 1 exists for credentials added after this file was written."""
    rec = logging.LogRecord("httpx", logging.INFO, __file__, 1,
                            "GET %s", ("https://example.org/x?api_key=NEVER_SEEN_BEFORE_9876",), None)
    out = _render(rec)
    assert "NEVER_SEEN_BEFORE_9876" not in out


def test_ordinary_parameters_are_untouched(redactor):
    """A redactor that mangles normal logs gets turned off, and then protects nothing."""
    url = "https://data.oceannetworks.ca/api?locationCode=SEIR&deviceCategoryCode=CTD&rowLimit=1"
    rec = logging.LogRecord("httpx", logging.INFO, __file__, 1, "GET %s", (url,), None)
    assert _render(rec) == f"GET {url}"


def test_numeric_arguments_keep_their_type(redactor):
    """⛔ Replacing an untouched int with a str makes the handler raise on %d —
    trading a leak for a crash. Formatting must still succeed."""
    rec = logging.LogRecord("x", logging.INFO, __file__, 1,
                            "%s took %d ms", ("job", 42), None)
    assert _render(rec) == "job took 42 ms"


def test_short_values_are_not_treated_as_secrets(monkeypatch):
    """A 4-character 'token' is a misconfiguration; redacting it would corrupt every
    line containing those four characters."""
    monkeypatch.setenv("ONC_TOKEN", "abcd")
    for name in ("FIRMS_MAP_KEY", "DATABASE_URL", "OPENAQ_API_KEY", "ABYSSAL_API_KEY",
                 "CMEMS_PASSWORD", "ADMIN_DASHBOARD_TOKEN", "ADMIN_BOOTSTRAP_PASSWORD",
                 "STRIPE_SECRET_KEY", "TELEGRAM_BOT_TOKEN", "MIRROR_PUSH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    importlib.reload(log_redaction)
    assert log_redaction.install() == 0
    assert log_redaction.redact("abcdefgh") == "abcdefgh"


def test_the_leak_is_reproducible_without_the_filter():
    """A green test is worthless if it cannot go red. With no filter installed, the
    token must appear in full — that is what production was doing."""
    importlib.reload(log_redaction)   # fresh module, install() never called
    url = "https://data.oceannetworks.ca/api?token=00000000-fake-4000-9000-000000000000"
    rec = logging.LogRecord("httpx", logging.INFO, __file__, 1, "GET %s", (url,), None)
    assert "00000000-fake-4000-9000-000000000000" in rec.getMessage()
