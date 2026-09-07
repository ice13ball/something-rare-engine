# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Every offshore sync reachable from the admin map must also be scheduled.

Six registries — pasa, esdm, cnh, nsta, crown_estate_scotland, sodir — were added
to the admin force-sync map on 2026-04-26 and never to the weekly loop. The loop
already carried sodir_co2 and nsta_co2, the CO2 variants of two of the SAME
authorities, which is exactly why nobody noticed: the names were there. They went
12-13 days stale with zero automatic attempts, and an audit had to find them.
"""
import inspect
import re

import main


def _loop_labels() -> set[str]:
    src = inspect.getsource(main._offshore_activities_sync_task)
    return set(re.findall(r'\(offshore\.\w+,\s*"([^"]+)"\)', src))


def _admin_offshore_labels() -> set[str]:
    """Admin entries whose lambda calls into `offshore.` — read from source, not
    from a hand-kept prefix list that would rot at the next naming style."""
    src = inspect.getsource(main)
    block = src[src.index("_SYNC_SOURCES = {"):]
    return set(re.findall(r'"([^"]+)":\s*lambda:\s*offshore\.\w+', block))


def test_the_admin_map_and_the_weekly_loop_are_not_empty():
    """Guards the regexes: if either returns nothing, the real test passes vacuously."""
    assert len(_admin_offshore_labels()) > 10
    assert len(_loop_labels()) > 10


def test_every_offshore_admin_source_is_also_scheduled():
    missing = _admin_offshore_labels() - _loop_labels()
    assert missing == set(), f"reachable by hand but never scheduled: {sorted(missing)}"
