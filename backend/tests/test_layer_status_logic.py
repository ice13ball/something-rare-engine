# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import pytest
from audit import validate_status, purge_allowed, sync_action_for_status, VALID_STATUSES


def test_valid_statuses():
    assert VALID_STATUSES == ("enabled", "disabled", "retired")
    validate_status("retired")  # no raise
    with pytest.raises(ValueError):
        validate_status("deleted")


def test_purge_blocked_when_enabled():
    ok, reason = purge_allowed("methane-seeps", "enabled")
    assert ok is False and "enabled" in reason.lower()


def test_purge_blocked_for_baked_layer():
    ok, reason = purge_allowed("marine-carbon", "retired")
    assert ok is False and "no data table" in reason.lower()


def test_purge_allowed_when_retired_with_table():
    ok, reason = purge_allowed("methane-seeps", "retired")
    assert ok is True and reason == ""


def test_retire_pauses_unretire_unpauses():
    assert sync_action_for_status("enabled", "retired", "seaflea") == "pause"
    assert sync_action_for_status("retired", "enabled", "seaflea") == "unpause"
    assert sync_action_for_status("enabled", "disabled", "seaflea") is None
    assert sync_action_for_status("enabled", "retired", None) is None  # no sync to pause
