# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from api_access import csrf


def test_csrf_ok_matches():
    t = csrf.new_csrf_token()
    assert csrf.csrf_ok(t, t) is True


def test_csrf_rejects_missing_or_mismatch():
    t = csrf.new_csrf_token()
    assert csrf.csrf_ok(None, t) is False
    assert csrf.csrf_ok(t, None) is False
    assert csrf.csrf_ok("", "") is False
    assert csrf.csrf_ok(t, t + "x") is False


def test_tokens_are_unique():
    assert csrf.new_csrf_token() != csrf.new_csrf_token()
