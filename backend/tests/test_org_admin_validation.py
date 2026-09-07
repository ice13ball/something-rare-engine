# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Input-validation constraints on the public org-admin request models.

Pure (no DB): just exercises the Pydantic models so the security hardening
(max_length on text fields, ge=1 on rate limits) can't silently regress.
"""
import pytest
from pydantic import ValidationError

from routers.org_admin_api import LoginBody, KeyBody, KeyPatchBody, PasswordBody


def test_login_body_bounds():
    LoginBody(username="alice", password="secret")  # ok
    with pytest.raises(ValidationError):
        LoginBody(username="", password="x")          # empty username
    with pytest.raises(ValidationError):
        LoginBody(username="a" * 65, password="x")    # username too long
    with pytest.raises(ValidationError):
        LoginBody(username="a", password="p" * 129)   # password too long


def test_key_body_rate_limits_reject_zero_and_negative():
    KeyBody(member_label="ci-bot")                                  # ok, no limits
    KeyBody(member_label="ci-bot", rate_limit_per_day=1000)         # ok
    with pytest.raises(ValidationError):
        KeyBody(member_label="ci-bot", rate_limit_per_day=0)        # 0 would brick the key
    with pytest.raises(ValidationError):
        KeyBody(member_label="ci-bot", rate_limit_per_min=-1)       # negative
    with pytest.raises(ValidationError):
        KeyBody(member_label="")                                    # empty label
    with pytest.raises(ValidationError):
        KeyBody(member_label="x" * 201)                            # label too long


def test_key_patch_body_bounds():
    KeyPatchBody()                                                  # all optional
    KeyPatchBody(notes="fine")
    with pytest.raises(ValidationError):
        KeyPatchBody(rate_limit_per_day=0)
    with pytest.raises(ValidationError):
        KeyPatchBody(notes="n" * 2001)                            # notes too long


def test_password_body_min_length_enforced():
    PasswordBody(current_password="oldsecret", new_password="newsecret1")  # ok
    with pytest.raises(ValidationError):
        PasswordBody(current_password="old", new_password="short")          # < 8 chars
