# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A source that stops refreshing must be distinguishable from one that never should.

Before this registry, `wdpa` sat 144 days stale behind an `if count > 0: return`
guard that was indistinguishable from the identical guard correctly protecting
`mining_footprints`, a one-off 2022 publication. Both looked like "working as
intended". Only one was.
"""
from datetime import datetime, timedelta, timezone

from ingestion.cadence import CADENCE, Blocked, Days, Static, should_sync

NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def test_static_never_resyncs_however_old():
    run, why = should_sync("mining_footprints", NOW - timedelta(days=3650), NOW)
    assert run is False
    assert "one-off" in why.lower() or "static" in why.lower()


def test_days_resyncs_once_the_window_has_elapsed():
    # `tailings_enrich` is a Days(90) source. This used `kbas` until 2026-09-03,
    # when that entry became Blocked — a Days test standing on a Blocked source
    # asserts nothing about windows.
    assert should_sync("tailings_enrich", NOW - timedelta(days=91), NOW)[0] is True
    assert should_sync("tailings_enrich", NOW - timedelta(days=89), NOW)[0] is False


def test_blocked_never_runs_and_says_why():
    run, why = should_sync("wdpa", NOW - timedelta(days=999), NOW)
    assert run is False
    assert "unep-wcmc" in why.lower()


def test_blocked_is_not_reported_as_a_cadence_skip():
    """A licence hold must not read as freshness, or someone will 'fix' it."""
    _, blocked_why = should_sync("wdpa", NOW - timedelta(days=999), NOW)
    _, fresh_why = should_sync("tailings_enrich", NOW - timedelta(days=1), NOW)
    assert blocked_why != fresh_why
    assert "blocked" in blocked_why.lower()


def test_never_synced_source_runs():
    assert should_sync("tailings_enrich", None, NOW)[0] is True


def test_unregistered_source_runs_rather_than_silently_skipping():
    """Forgetting to register a source must cost an extra sync, not silent staleness."""
    run, why = should_sync("brand_new_source", None, NOW)
    assert run is True
    assert "unregistered" in why.lower()


def test_static_and_a_long_days_window_are_not_the_same_type():
    """`Static` means 'never, and that is correct'. `Days(9999)` means 'rarely'.
    Only the second is a bug when it stops."""
    assert isinstance(CADENCE["mining_footprints"], Static)
    assert not isinstance(CADENCE["mining_footprints"], Days)


def test_every_registered_entry_carries_a_reason():
    for source, rule in CADENCE.items():
        assert rule.reason.strip(), f"{source} has no reason"


import inspect
import re
from pathlib import Path

import pytest

from domains.land import extractive, hazards


# Every land sync that may be gated, and the CADENCE key it must gate on.
#
# ⛔ A module-wide `assert "should_sync" in inspect.getsource(mod)` — which is
# what this file asserted until 2026-09-03 — passes when SEVEN of these eight
# gates are deleted. One surviving call satisfies the whole module. So the check
# is per-function, and the key each function passes is checked too: gating
# `dams` on the `tailings` window is a silent multi-month error a substring grep cannot
# see.
GATED_LAND_SYNCS: list[tuple[str, str]] = [
    ("extractive", "_sync_mining_footprints", "mining_footprints"),
    ("extractive", "_sync_kbas", "kbas"),
    ("extractive", "_sync_wdpa", "wdpa"),
    ("extractive", "_sync_tailings", "tailings"),
    ("extractive", "_enrich_tailings_from_grid", "tailings_enrich"),
    ("extractive", "_sync_dams", "dams"),
    ("hazards", "_sync_landslides", "landslides"),
    ("hazards", "_sync_water_risk", "water_risk"),
]

_MODULES = {"extractive": extractive, "hazards": hazards}


@pytest.mark.parametrize("mod_name,fn_name,source_key", GATED_LAND_SYNCS)
def test_each_land_sync_consults_the_registry_with_its_own_key(
    mod_name, fn_name, source_key
):
    """`if count > 0: return` cannot tell "finished publication" from "we stopped".

    Static sources may keep the row-count guard — it is their duplicate barrier —
    but it must no longer be the thing DECIDING whether to refresh.
    """
    fn = getattr(_MODULES[mod_name], fn_name)
    src = inspect.getsource(fn)
    assert f'should_sync("{source_key}"' in src, (
        f"{fn_name} does not consult CADENCE under its own key {source_key!r}"
    )


@pytest.mark.parametrize("mod_name,fn_name,source_key", GATED_LAND_SYNCS)
def test_each_land_sync_returns_when_the_registry_says_no(
    mod_name, fn_name, source_key
):
    """Calling should_sync and ignoring the answer is the same as not calling it.

    Asserting the CALL alone would pass against a function that logs `why` and
    then syncs anyway.
    """
    fn = getattr(_MODULES[mod_name], fn_name)
    src = inspect.getsource(fn)
    call = src.index("should_sync(")
    after = src[call:call + 400]
    assert "if not run:" in after, f"{fn_name} never acts on the registry's answer"
    assert "return" in after.split("if not run:", 1)[1][:80], (
        f"{fn_name} checks `run` but does not return early"
    )


@pytest.mark.parametrize("mod_name,fn_name,source_key", GATED_LAND_SYNCS)
def test_each_land_sync_passes_an_aware_now(mod_name, fn_name, source_key):
    """`sync_log.last_synced_at` is TIMESTAMPTZ, so asyncpg returns aware values.

    A naive `now` raises TypeError inside a sync whose caller catches Exception
    broadly — the source then goes stale silently, which is the exact failure
    this registry exists to end. Checked per function: one aware call elsewhere
    in the module says nothing about this one.
    """
    fn = getattr(_MODULES[mod_name], fn_name)
    src = inspect.getsource(fn)
    call = src.index("should_sync(")
    assert "datetime.now(timezone.utc)" in src[call:call + 200], (
        f"{fn_name} must pass a timezone-aware now to should_sync"
    )


def test_the_gated_list_has_not_drifted_from_the_modules():
    """Guard the guard: a sync added later must be added here, or the parametrised
    tests above simply never see it — the silent-staleness shape again."""
    for mod_name, mod in _MODULES.items():
        calls = re.findall(r'should_sync\("([^"]+)"', inspect.getsource(mod))
        listed = {k for m, _, k in GATED_LAND_SYNCS if m == mod_name}
        assert set(calls) == listed, (
            f"{mod_name}: GATED_LAND_SYNCS lists {sorted(listed)} but the module "
            f"gates {sorted(set(calls))}"
        )


def test_a_source_that_fetches_from_the_network_is_never_marked_static():
    """`Static` claims the upstream is a finished publication we hold a copy of.

    `tailings_enrich` was registered as Static("local derivation over rows we
    already hold"). It is not local: `_enrich_tailings_from_grid` GETs
    tailing.grida.no on every run and inserts facilities we do not hold. A false
    Static is worse than a missing entry — an unregistered source at least RUNS,
    while this one was permanently frozen behind a reason that read as correct.
    """
    import inspect

    from domains.land import extractive

    src = inspect.getsource(extractive._enrich_tailings_from_grid)
    fetches_remotely = "GRID_TAILINGS_API" in src or "http" in src
    assert fetches_remotely, "test premise stale — this function no longer fetches"
    assert isinstance(CADENCE["tailings_enrich"], Days), (
        "tailings_enrich fetches a live upstream; Static freezes it forever"
    )
    assert "grida" in CADENCE["tailings_enrich"].reason.lower(), (
        "the reason must name the upstream it fetches, or the next reader "
        "re-derives the same wrong conclusion"
    )


# ── force: a bypass for the cadence gate, never for the licence hold ─────────

def test_force_bypasses_a_fresh_cadence_window():
    """Without this the admin Force Sync button was a silent no-op.

    Every `land-*` entry in `_SYNC_SOURCES` calls its sync with no arguments, so
    the button hit the same cadence gate as the scheduler and returned 0 — while
    the admin panel and the Mac staleness monitor both reported success. A
    control that reports success and does nothing is worse than no control.
    """
    run, why = should_sync("tailings_enrich", NOW - timedelta(days=1), NOW, force=True)
    assert run is True
    assert "forc" in why.lower()


def test_force_does_not_bypass_a_blocked_source():
    """⛔ A licence hold must stay unfetchable even by hand.

    `wdpa` is Blocked because Protected Planet requires written permission we do
    not have. If Force Sync could reach it, the withdrawal would be one admin
    click deep — and the click would look like routine maintenance.
    """
    run, why = should_sync("wdpa", NOW - timedelta(days=999), NOW, force=True)
    assert run is False
    assert "blocked" in why.lower()


def test_force_does_not_bypass_a_blocked_source_that_was_never_synced():
    """last_synced_at=None is the other route past a freshness check."""
    run, _ = should_sync("wdpa", None, NOW, force=True)
    assert run is False


def test_force_runs_a_static_source():
    """Static means "no schedule", not "never by hand" — a one-off publication
    still has to be loadable the first time, and re-loadable after a restore."""
    assert should_sync("mining_footprints", NOW, NOW, force=True)[0] is True


@pytest.mark.parametrize("mod_name,fn_name,source_key", GATED_LAND_SYNCS)
def test_each_gated_land_sync_accepts_force(mod_name, fn_name, source_key):
    fn = getattr(_MODULES[mod_name], fn_name)
    params = inspect.signature(fn).parameters
    assert "force" in params, f"{fn_name} cannot be forced"
    assert params["force"].default is False, (
        f"{fn_name}: force must default to False — the scheduler calls it too"
    )
    src = inspect.getsource(fn)
    call = src.index("should_sync(")
    assert "force=force" in src[call:call + 200], (
        f"{fn_name} takes force but does not pass it to the registry"
    )


def test_the_admin_force_sync_map_actually_forces_the_land_syncs():
    """The bug was here: `lambda: _sync_kbas()` with no argument."""
    src = (Path(__file__).resolve().parent.parent / "main.py").read_text()
    block = src[src.index("_SYNC_SOURCES"):]
    block = block[:block.index("\n}\n")]
    offenders = []
    for line in block.splitlines():
        if '"land-' not in line or "lambda" not in line:
            continue
        # land-all and land-overlaps are orchestrators, not cadence-gated syncs
        if '"land-all"' in line or '"land-overlaps"' in line:
            continue
        if "force=True" not in line:
            offenders.append(line.strip())
    assert offenders == [], f"admin force-sync entries that do not force: {offenders}"
