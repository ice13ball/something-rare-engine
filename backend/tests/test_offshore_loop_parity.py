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
import scheduling


def _loop_labels() -> set[str]:
    # 2026-09-18: _offshore_activities_sync_task moved to scheduling.py as
    # part of the web/worker split, and its per-source (fn, label) tuples
    # moved out of the function body into the module-level
    # OFFSHORE_ACTIVITIES_SOURCES list it now iterates — read that list
    # directly rather than regexing the function's source, which no longer
    # contains the tuples at all (inspect.getsource would just find the
    # `for fn, label in OFFSHORE_ACTIVITIES_SOURCES:` line and match nothing,
    # passing vacuously — exactly the failure mode
    # test_the_admin_map_and_the_weekly_loop_are_not_empty exists to catch).
    return {label for _fn, label in scheduling.OFFSHORE_ACTIVITIES_SOURCES}


def _admin_offshore_labels() -> set[str]:
    """Admin entries whose lambda calls into `offshore.` — read from source, not
    from a hand-kept prefix list that would rot at the next naming style."""
    # 2026-09-18: the dict moved from main.py to sync_sources.py so the WORKER
    # process can read it without importing main (which constructs the FastAPI
    # app). main.py still re-exports it as `_SYNC_SOURCES`, so this has to read
    # the module that holds the literal, not the one that re-exports the name.
    import sync_sources
    src = inspect.getsource(sync_sources)
    block = src[src.index("SYNC_SOURCES: dict"):]
    return set(re.findall(r'"([^"]+)":\s*lambda:\s*offshore\.\w+', block))


def test_the_admin_map_and_the_weekly_loop_are_not_empty():
    """Guards the regexes: if either returns nothing, the real test passes vacuously."""
    assert len(_admin_offshore_labels()) > 10
    assert len(_loop_labels()) > 10


def test_every_offshore_admin_source_is_also_scheduled():
    missing = _admin_offshore_labels() - _loop_labels()
    assert missing == set(), f"reachable by hand but never scheduled: {sorted(missing)}"
