# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Every Force Sync mapping must point at an action that exists.

_SOURCE_TO_ACTION (main.py) maps a sync_log source to the admin action that
re-runs it; SYNC_SOURCES (sync_sources.py) holds the actions. A value that is
not a key there makes the dashboard's Force Sync button do nothing, with no
error anywhere. On 2026-09-23 "dea-dk" was mapped to "dea-dk-petroleum", an
action that never existed; only this lookup caught it.
"""
import main
import sync_sources


def test_every_mapped_action_exists():
    missing = {
        source: action
        for source, action in main._SOURCE_TO_ACTION.items()
        if action not in sync_sources.SYNC_SOURCES
    }
    assert missing == {}
