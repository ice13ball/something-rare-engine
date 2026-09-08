# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The one ordered list of schema steps, and the runner both callers share.

⛔ ORDER IS SEMANTICS. An index or ALTER ahead of its CREATE TABLE fails, which
is the exact class of bug a schema step exists to catch. `schema/__init__.py`
says the same about the order inside `ensure_schema`, and
`tests/test_ensure_schema_ddl.py` snapshots it.

This module must stay importable with no application context: `scripts/migrate.py`
imports it before the app runs, and importing `main` from here would be circular
through `land_layers`.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

from schema import ensure_schema
from api_access.schema import ensure_api_access_schema
from api_access.logstore import ensure_log_schema
from api_access.admin_auth import ensure_admin_schema
from startup_seeds import ensure_layer_config_seed, ensure_startup_profiles_seed
from layer_temporal_coverage import ensure_layer_temporal_coverage
from domains.land.schema_orchestrator import ensure_land_schema
from land_overlaps import ensure_overlap_views
from vessel_events import ensure_vessel_events_schema
from sar_detector import ensure_sar_schema
from ais_sync import ensure_ais_schema
from domains.land.density import (
    ensure_density_hex_cells,
    ensure_density_source_indexes,
    ensure_monitoring_density_matview,
)
# ⛔ routers/reports.py is Impact Reports v1 — frozen. Import only; never edit.
from routers.reports import ensure_species_cache_table


Step = Callable[[], Awaitable[None]]

SCHEMA_STEPS: tuple[tuple[Step, str], ...] = (
    (ensure_schema,                     "ensure_schema"),
    (ensure_api_access_schema,          "ensure_api_access_schema"),
    (ensure_log_schema,                 "ensure_log_schema"),
    (ensure_admin_schema,               "ensure_admin_schema"),
    (ensure_layer_config_seed,          "ensure_layer_config_seed"),
    # Runs right after layer_config: both describe layers, and this one answers the
    # question layer_config cannot — WHEN each layer's data is from.
    (ensure_layer_temporal_coverage,    "ensure_layer_temporal_coverage"),
    (ensure_startup_profiles_seed,      "ensure_startup_profiles_seed"),
    (ensure_land_schema,                "ensure_land_schema"),
    (ensure_overlap_views,              "ensure_overlap_views"),
    (ensure_vessel_events_schema,       "ensure_vessel_events_schema"),
    (ensure_sar_schema,                 "ensure_sar_schema"),
    (ensure_ais_schema,                 "ensure_ais_schema"),
    (ensure_density_hex_cells,          "ensure_density_hex_cells"),
    (ensure_density_source_indexes,     "ensure_density_source_indexes"),
    (ensure_monitoring_density_matview, "ensure_monitoring_density_matview"),
    (ensure_species_cache_table,        "ensure_species_cache_table"),
)


# ── schema_migrations: the one row both DB-provisioning scripts write ──────
# Shared here (not duplicated in each script) so `scripts/migrate.py` and
# `scripts/ci_bootstrap_db.py` write the identical row in the identical shape.
# Without this, a fresh database bootstrapped by ci_bootstrap_db.py never got
# a schema_migrations row at all: `_fetch_schema_migration_row` in main.py
# caught UndefinedTableError, returned None, and /health reported
# `{"status":"ok","schema":"stale"}` permanently — the alarm stuck on in
# exactly the environments (CI, any new env) where nothing was wrong.
MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id          INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    applied_at  TIMESTAMPTZ NOT NULL,
    git_sha     TEXT NOT NULL,
    steps       INTEGER NOT NULL
)
"""


async def ensure_schema_migrations_table(conn) -> None:
    """Create schema_migrations if it doesn't exist yet. Idempotent."""
    await conn.execute(MIGRATIONS_DDL)


async def record_schema_migration(conn, sha: str, steps: int) -> None:
    """Upsert the single schema_migrations row. Both callers must run this
    AFTER every step in SCHEMA_STEPS has succeeded — recording it earlier
    would let /health report "ok" for a schema that isn't actually there yet."""
    await conn.execute(
        """INSERT INTO schema_migrations (id, applied_at, git_sha, steps)
           VALUES (1, now(), $1, $2)
           ON CONFLICT (id) DO UPDATE
             SET applied_at = EXCLUDED.applied_at,
                 git_sha    = EXCLUDED.git_sha,
                 steps      = EXCLUDED.steps""",
        sha, steps,
    )


def _looks_like_sha(s: str) -> bool:
    """A git object id: 40 hex chars (SHA-1) or 64 (SHA-256 repos)."""
    return len(s) in (40, 64) and all(c in "0123456789abcdefABCDEF" for c in s)


def _read_git_head_sha(repo) -> str | None:
    """Resolve HEAD by reading `.git` directly — no subprocess.

    Handles a `.git` directory (the normal case) and a `.git` *file* — a
    worktree pointer, `gitdir: <path>` — by following it one level. It does
    NOT chase a worktree pointer that itself points at another pointer;
    that shape doesn't occur in a deploy checkout and isn't worth the extra
    branch. Returns None for anything it doesn't handle, including any I/O
    error reading these files — the caller falls back to the `git` binary,
    then to None.
    """
    import pathlib

    dotgit = repo / ".git"
    if dotgit.is_file():
        try:
            content = dotgit.read_text().strip()
        except OSError:
            return None
        if not content.startswith("gitdir:"):
            return None
        target = pathlib.Path(content.split(":", 1)[1].strip())
        gitdir = target if target.is_absolute() else (dotgit.parent / target)
    elif dotgit.is_dir():
        gitdir = dotgit
    else:
        return None

    try:
        head = (gitdir / "HEAD").read_text().strip()
    except OSError:
        return None

    if not head.startswith("ref:"):
        # Detached HEAD: the raw SHA is written directly.
        return head if _looks_like_sha(head) else None

    ref = head.split(":", 1)[1].strip()  # e.g. "refs/heads/dev"
    ref_file = gitdir / ref
    if ref_file.is_file():
        try:
            sha = ref_file.read_text().strip()
        except OSError:
            return None
        return sha if _looks_like_sha(sha) else None

    # No loose ref file — a gc packed it. packed-refs lines look like
    # "<sha> <ref>", with occasional "^<sha>" peel lines for annotated tags
    # (never immediately relevant to a branch ref, but skipped regardless).
    packed = gitdir / "packed-refs"
    if not packed.is_file():
        return None
    try:
        lines = packed.read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line or line[0] in "#^":
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1] == ref and _looks_like_sha(parts[0]):
            return parts[0]
    return None


def resolve_git_sha() -> str | None:
    """Which commit this tree is. None when the answer is genuinely unknowable.

    Lives here, not in scripts/migrate.py, because BOTH the migration script and
    lifespan() need it. Importing it from the deploy script would make the
    running application depend on the thing that deploys it.

    Resolution order:
      1. ABYSSAL_GIT_SHA from the environment, if set.
      2. Read `.git` on disk directly (`_read_git_head_sha`) — deliberately
         subprocess-free. The abyssal-api systemd unit sets `PATH` to just
         the venv's bin/ so its own python/uvicorn win; `git` is not on it,
         so a `git` subprocess call there always raised FileNotFoundError
         and this function silently returned None on every production boot
         (verified 2026-09: schema_migrations held the running commit, but
         /health reported "unknown" instead of "ok" — the check was correct
         and permanently blind at once).
      3. The `git` binary, as a last resort, for whatever the on-disk read
         didn't handle (packed-refs edge cases, a shallow clone, etc.) — it
         works fine on a developer machine and in CI, where PATH is normal.
      4. None, if nothing above answers. A tarball deploy with no `.git` and
         no env var genuinely cannot know its commit.
    """
    import os
    import pathlib
    import subprocess

    env = os.environ.get("ABYSSAL_GIT_SHA")
    if env:
        return env

    repo = pathlib.Path(__file__).resolve().parent.parent

    sha = _read_git_head_sha(repo)
    if sha:
        return sha

    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def is_lock_error(exc: BaseException) -> bool:
    """A lock timeout, whatever driver wrapper it arrives in."""
    text = f"{type(exc).__name__}: {exc}".lower()
    return "lock" in text and ("timeout" in text or "canceling statement" in text)


async def run_step(step: Step, name: str, *, timeout_s: float) -> float:
    """Run one schema step under a wall-clock guard. Returns seconds elapsed.

    Always raises on a lock conflict — never skips. `scripts/migrate.py` is the
    only caller (lifespan() no longer runs schema steps at all; ci_bootstrap_db.py
    calls the step functions directly, without this wrapper), so there is exactly
    one place a lock conflict can be handled, and failing is the only correct
    answer there: a skipped step would let the deploy restart onto a schema the
    code does not expect. That is precisely what happened on 2026-09-06 at 15:28
    — the (now-removed) startup path tolerated a lock timeout on one step and
    deferred it "to next restart", and the API went on to serve a whole day on a
    schema it did not expect, silently. migrate.py's own retry loop is the
    correct response to a lock: the old process is still serving and holding
    locks, so wait and try again — never skip.

    ⚠️ The wall-clock guard is not redundant with lock_timeout. Only 4 of the 16
    steps set lock_timeout on their own connection; the other eleven wait
    forever, and on 2026-08-21 that meant lifespan() never returned, uvicorn
    never bound the port, and systemctl reported `active` while nothing
    listened. A crash-loop is loud; that hang was silent.
    """
    started = time.monotonic()
    try:
        await asyncio.wait_for(step(), timeout=timeout_s)
    except asyncio.TimeoutError:
        raise TimeoutError(f"{name} exceeded {timeout_s:.0f}s") from None
    return time.monotonic() - started
