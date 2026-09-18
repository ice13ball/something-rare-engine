# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The background-task registry (scheduling.TASK_REGISTRY) is the ONLY
thing allowed to decide which background tasks a process starts.

Two failure modes this guards:

1. **A rogue create_task.** Before this refactor, `main.py`'s `lifespan()`
   had 43 literal `asyncio.create_task(...)` call sites, one per task, with
   ABYSSAL_STANDBY as the only gate. It is now ONE call site, inside a loop
   over `scheduling.tasks_for_role(role)` — so a future task that gets a
   second, hand-written `asyncio.create_task(...)` directly in `lifespan()`
   (bypassing the registry, the exact "flag scattered through the code"
   shape this task was asked NOT to reproduce) makes that count 2, which
   `test_lifespan_has_exactly_one_create_task_call_site` below catches by
   walking `lifespan()`'s AST — it does not need to know the new task's
   name to fail.

2. **Silent registry drift.** `test_default_role_matches_todays_full_set`
   hardcodes the 44 names this audit found on 2026-09-18 (43 pre-existing
   tasks + the memory-peak sampler added the same day) so an accidental
   removal — or a name typo that orphans an entry — fails loudly instead of
   quietly changing what ships under the default role ("all").

⛔ Every assertion below must be reachable by deleting or mislabelling one
registry entry, or by changing the default role. See the sabotage log in
the PR description for the counts each of those actually produced.
"""
from __future__ import annotations

import ast
import asyncio
import logging
import re
from pathlib import Path

import pytest

import scheduling

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_MAIN_PY = _BACKEND_DIR / "main.py"
_WORKER_PY = _BACKEND_DIR / "worker.py"

# The full set this audit found on 2026-09-18: 43 tasks reachable from the
# pre-refactor lifespan() (recounted via `grep -c asyncio.create_task`
# against the ORIGINAL main.py, minus the one call site that is NOT inside
# lifespan() — /admin/sync/{source}'s _run_tracked, which stays a plain
# create_task in main.py and is deliberately outside this registry, it is
# an admin-triggered one-off, not a scheduled background task) plus the
# memory-peak sampler added the same day.
#
# 2026-09-18, later the same day: "sync-request-listener" joined them, and the
# note above about /admin/sync/{source} "staying a plain create_task in main.py"
# is now HISTORY — that endpoint no longer runs anything. It writes a row and
# NOTIFYs; the listener below is what claims the row and runs the sync, in the
# worker. See sync_queue.py.
_EXPECTED_ALL_TASK_NAMES = {
    "sync-request-listener",
    "contractor-auto-discovery", "request-log-batch-writer", "usage-rollup",
    "leak-detection", "log-retention", "startup-data-check",
    "weekly-sync-chain", "argo-12h-sync", "argo-history-floor",
    "argo-history-backfill", "worms-taxonomy-sync", "sio-bic-catalogue-sync",
    "slow-sources-daily-tick", "monitoring-density-refresh",
    "land-layers-sync", "currents-daily-bake", "currents-history-backfill",
    "woa-startup-bake", "woa-anomaly-backfill", "carbon-startup-bake",
    "acidification-startup-bake", "chi-startup-bake",
    "coral-exposure-startup-bake", "socat-startup-bake",
    "seabed-startup-bake", "cascade-startup-bake",
    "bathymetry-grid-startup-bake", "oxygen-startup-bake",
    "onc-sensor-daily-sync", "onc-instruments-daily", "onc-sparkline-refresh",
    "onc-adcp-refresh", "onc-ctd-refresh", "onc-ctd-series-archive",
    "usgs-earthquakes-sync", "oceansites-obs-daily-sync",
    "air-quality-readings-drip", "acoustic-stations-weekly-sync",
    "acoustic-soundscape-weekly-sync", "offshore-activities-weekly-sync",
    "noise-risk-count-startup-log", "query-watchdog", "offshore-tile-prebake",
    "memory-peak-sampler",
}

_EXPECTED_WEB_ONLY = {"request-log-batch-writer"}
_EXPECTED_BOTH = {"startup-data-check"}


# ─────────────────────────────────────────────────────────────────────────────
# 1. The registry IS the wiring — lifespan() has no rogue create_task call.
# ─────────────────────────────────────────────────────────────────────────────

def _find_lifespan_func(tree: ast.Module) -> ast.AsyncFunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan":
            return node
    raise AssertionError("main.py has no `async def lifespan` anymore — update this test")


def _create_task_call_sites(func: ast.AST) -> list[ast.Call]:
    """Every Call node anywhere inside `func` whose callee is
    `asyncio.create_task` (attribute access) or a bare `create_task` name."""
    sites = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        is_asyncio_create_task = (
            isinstance(f, ast.Attribute) and f.attr == "create_task"
            and isinstance(f.value, ast.Name) and f.value.id == "asyncio"
        )
        if is_asyncio_create_task:
            sites.append(node)
    return sites


def test_lifespan_has_exactly_one_create_task_call_site():
    """Every task reachable from lifespan() goes through the registry loop.

    Walking the AST can't tell us the 43 task NAMES any more (they're not
    literal arguments any more — the loop calls `spec.factory(ctx)`), but it
    CAN tell us there is exactly one place in lifespan() that calls
    asyncio.create_task at all. A 44th (or 45th) task wired in by hand,
    bypassing scheduling.TASK_REGISTRY, would be a SECOND call site and
    fail this — which is the actual danger this test exists to catch.
    """
    tree = ast.parse(_MAIN_PY.read_text())
    lifespan = _find_lifespan_func(tree)
    sites = _create_task_call_sites(lifespan)
    assert len(sites) == 1, (
        f"expected exactly 1 asyncio.create_task call site in lifespan(), "
        f"found {len(sites)} — every scheduled task must start through "
        f"scheduling.TASK_REGISTRY's loop, not a hand-written call"
    )
    # And that one call site must be inside a `for` loop (the registry
    # iteration), not a bare top-level call — otherwise "one call site"
    # could still mean "one task", which would silently drop the other 43.
    site = sites[0]
    ancestors_are_for_loop = any(
        isinstance(n, ast.For) and site in list(ast.walk(n))
        for n in ast.walk(lifespan)
    )
    assert ancestors_are_for_loop, (
        "the sole asyncio.create_task call in lifespan() must be inside a "
        "for-loop over the registry, not a single hardcoded call"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Registry shape: no dupes, only three valid roles.
# ─────────────────────────────────────────────────────────────────────────────

def test_no_task_is_labelled_twice():
    names = [t.name for t in scheduling.TASK_REGISTRY]
    dupes = {n for n in names if names.count(n) > 1}
    assert dupes == set(), f"duplicate task name(s) in TASK_REGISTRY: {dupes}"


def test_every_role_is_one_of_the_three_values():
    valid = {scheduling.ROLE_WEB, scheduling.ROLE_WORKER, scheduling.ROLE_BOTH}
    bad = {t.name: t.role for t in scheduling.TASK_REGISTRY if t.role not in valid}
    assert bad == {}, f"task(s) with an invalid role: {bad}"


def test_every_task_has_a_non_empty_reason():
    empty = [t.name for t in scheduling.TASK_REGISTRY if not t.reason or not t.reason.strip()]
    assert empty == [], f"task(s) with no classification reason: {empty}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Role filtering produces the right subsets.
# ─────────────────────────────────────────────────────────────────────────────

def test_web_role_yields_batch_writer_not_the_syncs():
    names = {t.name for t in scheduling.tasks_for_role("web")}
    assert _EXPECTED_WEB_ONLY <= names
    assert "weekly-sync-chain" not in names
    assert "argo-history-backfill" not in names
    assert "offshore-activities-weekly-sync" not in names


def test_worker_role_yields_the_syncs_not_batch_writer():
    names = {t.name for t in scheduling.tasks_for_role("worker")}
    assert "request-log-batch-writer" not in names
    assert "weekly-sync-chain" in names
    assert "argo-history-backfill" in names
    assert "offshore-activities-weekly-sync" in names


def test_both_role_tasks_appear_under_web_and_worker():
    web_names = {t.name for t in scheduling.tasks_for_role("web")}
    worker_names = {t.name for t in scheduling.tasks_for_role("worker")}
    assert _EXPECTED_BOTH <= web_names
    assert _EXPECTED_BOTH <= worker_names


def test_default_role_matches_todays_full_set():
    """role="all" (the default — see main.py's `os.environ.get("ABYSSAL_ROLE",
    "all")`) must yield exactly today's full set, so this switch existing
    cannot silently change default behaviour."""
    names = {t.name for t in scheduling.tasks_for_role("all")}
    assert names == _EXPECTED_ALL_TASK_NAMES


def test_unknown_role_raises():
    with pytest.raises(ValueError):
        scheduling.tasks_for_role("standby")  # not a role — see module docstring


def test_main_py_defaults_abyssal_role_to_all():
    """`scheduling.tasks_for_role("all")` returning today's full set is not
    enough on its own — main.py has to actually ASK for "all" when
    ABYSSAL_ROLE is unset, or every claim above is true of a role nothing
    ever requests. Caught live: sabotaging main.py's default to "web"
    produced ZERO failures elsewhere in this file, because every other test
    calls scheduling.tasks_for_role() directly and never reads main.py's
    literal default. This is the one test that reads main.py's own source
    for the `os.environ.get("ABYSSAL_ROLE", ...)` call and checks the
    literal default argument — not importable-and-callable without a live
    DB (lifespan() opens a real pool), so source inspection is what's left.
    """
    tree = ast.parse(_MAIN_PY.read_text())
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
        and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "environ"
        and len(node.args) == 2 and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "ABYSSAL_ROLE"
    ]
    assert len(calls) == 1, (
        f"expected exactly one os.environ.get('ABYSSAL_ROLE', ...) call in "
        f"main.py, found {len(calls)}"
    )
    default_arg = calls[0].args[1]
    assert isinstance(default_arg, ast.Constant) and default_arg.value == "all", (
        f"main.py's ABYSSAL_ROLE default is {getattr(default_arg, 'value', default_arg)!r}, "
        f"not \"all\" — local dev and the pre-split test suite assumed "
        f"every task starts with no environment configured at all"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. worker.py cannot start a web server.
# ─────────────────────────────────────────────────────────────────────────────

def test_worker_entrypoint_does_not_import_main_or_fastapi_app():
    """Behavioural test can't see this: constructing `FastAPI()` doesn't
    bind a port or do anything externally observable by itself — the harm
    is only that `main.py`'s import triggers `app = FastAPI(...)` plus every
    `app.add_middleware`/`app.include_router` call as a module-level side
    effect. So this has to be a source/import-graph assertion: worker.py
    must never import `main` (directly or by name in an import statement),
    and must never call `uvicorn.run`/bind a socket itself.

    NOT asserting "worker.py never touches the `fastapi` package
    transitively" — several domain modules (e.g. domains/acoustic.py) define
    their own `APIRouter` in the same file as their sync functions, and
    scheduling.py legitimately imports those modules for the sync side. That
    router object is never mounted or served by worker.py; only importing
    `main` (which DOES construct and wire up the live `app`) is the danger.
    """
    tree = ast.parse(_WORKER_PY.read_text())
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    assert "main" not in imported_modules, (
        "worker.py must not import main.py — that import alone constructs "
        "the FastAPI app as a module-level side effect"
    )
    assert not any(m == "fastapi" or m.startswith("fastapi.") for m in imported_modules), (
        "worker.py itself must not import fastapi directly"
    )
    # Checked via the import list, not a raw substring search on the file
    # text — this module's own docstring mentions "uvicorn.run" in prose to
    # explain what main.py's import graph risks, which a naive text search
    # would trip over.
    assert not any(m == "uvicorn" or m.startswith("uvicorn.") for m in imported_modules), (
        "worker.py must not import uvicorn / start a web server"
    )


def test_worker_module_actually_imports():
    """`ast.parse`/`py_compile` only check syntax — they do not catch an
    import of a name that doesn't exist in the module it's imported from.
    That exact bug shipped once during this task's own development
    (`from scheduling import ..., _load_paused_syncs` — scheduling.py never
    defined it) and every syntax-only check passed anyway. Actually
    importing the module is the only check that catches it."""
    import importlib
    import worker as worker_mod
    importlib.reload(worker_mod)
    assert callable(worker_mod.main)


def test_scheduling_module_itself_never_imports_main():
    """scheduling.py is imported by BOTH main.py and worker.py — if it ever
    imported main.py back, that would be a circular import (main imports
    scheduling, scheduling imports main) that Python might paper over
    depending on import order, silently reintroducing the exact problem
    worker.py exists to avoid. Assert the source directly rather than rely
    on import order happening to work."""
    text = (_BACKEND_DIR / "scheduling.py").read_text()
    assert re.search(r"^\s*(import main\b|from main import)", text, re.MULTILINE) is None


# ─────────────────────────────────────────────────────────────────────────────
# 5. Memory-peak sampler: attribution and unit normalisation.
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("platform, raw, expected_kb", [
    ("linux", 123_456, 123_456),      # Linux ru_maxrss is already KB
    ("linux2", 1, 1),                  # legacy sys.platform spelling, still Linux-shaped
    ("darwin", 123_456 * 1024, 123_456),  # macOS ru_maxrss is BYTES
])
def test_maxrss_normalisation_is_platform_correct(platform, raw, expected_kb):
    got = scheduling._normalize_maxrss_kb(raw, platform=platform)
    assert got == expected_kb, (
        f"platform={platform}: got {got} KB from raw={raw}, expected {expected_kb} KB "
        f"— ru_maxrss units differ by platform (KB on Linux, bytes on Darwin); "
        f"an off-by-1024x here is exactly the kind of wrong-but-precise-looking "
        f"number this sampler exists to avoid producing"
    )


def test_observe_rss_reports_delta_only_on_rise():
    # Rising sample: reports the new peak and a positive delta.
    peak, delta = scheduling._observe_rss(rss_kb=500, prev_peak_kb=400)
    assert peak == 500 and delta == 100
    # Falling sample: peak unchanged, delta is None (must NOT log).
    peak, delta = scheduling._observe_rss(rss_kb=300, prev_peak_kb=500)
    assert peak == 500 and delta is None
    # Flat sample: same, no rise, no log.
    peak, delta = scheduling._observe_rss(rss_kb=500, prev_peak_kb=500)
    assert peak == 500 and delta is None


@pytest.mark.asyncio
async def test_memory_sampler_logs_once_per_rise_not_per_sample(caplog):
    """Drive the real async sampler with a stubbed reader: rising, rising,
    flat, falling, rising. Exactly 3 rises → exactly 3 log lines, none for
    the flat/falling samples. Ends the loop by having the stub raise
    CancelledError once the sequence is exhausted, same as a real task
    cancellation would."""
    sequence = [100, 200, 200, 150, 400]
    it = iter(sequence)

    def reader():
        try:
            return next(it)
        except StopIteration:
            raise asyncio.CancelledError

    scheduling._peak_rss_kb = 0  # reset module state between tests
    caplog.set_level(logging.WARNING, logger=scheduling.log.name)
    with pytest.raises(asyncio.CancelledError):
        await scheduling._memory_peak_sampler(read_rss=reader, interval=0)

    watermark_lines = [r for r in caplog.records if "memory watermark: new peak" in r.message]
    assert len(watermark_lines) == 3, (
        f"expected exactly 3 rise-logged lines for sequence {sequence}, "
        f"got {len(watermark_lines)}: {[r.message for r in watermark_lines]}"
    )


@pytest.mark.asyncio
async def test_lock_holder_is_set_during_and_cleared_after_success():
    assert scheduling._lock_holder is None
    async with scheduling._held_sync_lock("test-sync"):
        assert scheduling._lock_holder == "test-sync"
    assert scheduling._lock_holder is None


@pytest.mark.asyncio
async def test_lock_holder_is_cleared_even_when_the_sync_raises():
    """A name that survives a crash would blame the wrong sync forever —
    the exact failure mode the module docstring calls out."""
    assert scheduling._lock_holder is None
    with pytest.raises(RuntimeError):
        async with scheduling._held_sync_lock("test-sync-that-fails"):
            assert scheduling._lock_holder == "test-sync-that-fails"
            raise RuntimeError("boom")
    assert scheduling._lock_holder is None
