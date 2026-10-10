# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The worker decisions that exist nowhere else and fail silently: a killed run with files still pending RESUMES
(no 7-day back-off), a file killed twice is not retried for ever, the quarterly check is not a daily one, the LOD
rebuild is due exactly when a file was loaded after it, and the unit's timeout is the worker's stale marker."""
import configparser
import importlib
import pathlib
from datetime import timedelta

import wod_casts_worker as w
from ingestion import wod_casts_rules as R
from wod_helpers import CUT_OF, conn, db, needs_db, register  # noqa: F401  (fixtures)

REPO = pathlib.Path(__file__).resolve().parents[2]
NAMES = sorted(CUT_OF)


@needs_db
async def test_interrupted_with_pending_files_resumes(db):
    fid = await register(db, NAMES[0])
    assert await w._stamp_interrupt(db, fid) == 1               # the run that was then killed stamped it
    assert await db.fetchval("SELECT last_failure FROM wod_casts_source") == "interrupted"
    assert await w._decide(db) == "resume"
    # nothing left to import: the same stamp is a plain back-off, not a resume
    await db.execute("UPDATE wod_files SET status = 'missing'")
    assert await w._decide(db) == "backoff"


@needs_db
async def test_same_file_interrupted_twice_backs_off(db, monkeypatch):
    a, b = await register(db, NAMES[0]), await register(db, NAMES[1])
    alerts = []

    async def fake_notify(msg, title=None):
        alerts.append(msg)
    monkeypatch.setattr(w, "notify_telegram", fake_notify)
    assert await w._stamp_interrupt(db, a) == 1
    assert await w._stamp_interrupt(db, a) == 2                 # the resumed run was killed too
    assert await w._decide(db) == "backoff"
    await w._settle_double_interrupt(db)                         # alerts once and keeps the 7-day back-off
    await w._settle_double_interrupt(db)
    assert len(alerts) == 1 and "interrupted twice at file" in alerts[0] and NAMES[0] in alerts[0]
    assert await w._decide(db) == "backoff"
    # another file restarts the count
    assert await w._stamp_interrupt(db, b) == 1
    assert await w._decide(db) == "resume"


@needs_db
async def test_quarterly_check_only_after_91_days(db):
    await db.execute("UPDATE wod_casts_source SET loaded_at = now(), tile_built_at = now(), "
                     "last_checked_at = now() - interval '90 days'")
    assert await w._decide(db) == "fresh"
    assert await w._decide(db, forced_check=True) == "check"      # --check
    await db.execute("UPDATE wod_casts_source SET last_checked_at = now() - interval '92 days'")
    assert await w._decide(db) == "check"


@needs_db
async def test_lod_due_exactly_when_a_file_loaded_after_the_cells_were_built(db):
    fid = await register(db, NAMES[0])
    await db.execute("UPDATE wod_files SET status = 'loaded', loaded_at = now() WHERE file_id = $1", fid)
    await db.execute("UPDATE wod_casts_source SET loaded_at = now(), last_checked_at = now(), "
                     "tile_built_at = now() - interval '1 hour'")
    assert await w._decide(db) == "lod due"                      # P3: only the rebuild runs
    await db.execute("UPDATE wod_casts_source SET tile_built_at = now() + interval '1 hour'")
    assert await w._decide(db) == "fresh"
    # a version whose bake never succeeded: only the bake is due; a good (or timed-out) bake since then ends it
    await db.execute("UPDATE wod_casts_source SET tile_version = 'v1'")
    assert await w._decide(db) == "bake due"
    await db.execute("INSERT INTO sync_log (source, last_synced_at, skipped_reason, skipped_at) "
                     "VALUES ('wod-tiles', now() - interval '3 hours', 'skipped: 4 tiles timed out', now() + interval '2 hours')")
    assert await w._decide(db) == "fresh"


@needs_db
async def test_a_start_marker_is_a_live_run_for_the_whole_unit_timeout(db, monkeypatch):
    async def alive(conn):
        return True
    monkeypatch.setattr(w, "_worker_alive", alive)
    await db.execute("INSERT INTO sync_log (source, skipped_reason, skipped_at) "
                     "VALUES ('wod-casts', 'started (pending)', now() - interval '7 hours 50 minutes')")
    assert await w._decide(db) == "running"
    await db.execute("UPDATE sync_log SET skipped_at = now() - interval '8 hours 10 minutes' "
                     "WHERE source = 'wod-casts'")
    assert await w._decide(db) != "running"                      # a killed run's marker lapses
    # a fresh marker with no live worker connection (systemctl stop, OOM) must not block the next run
    await db.execute("UPDATE sync_log SET skipped_at = now() WHERE source = 'wod-casts'")
    assert await w._decide(db) == "running"
    monkeypatch.undo()
    assert await w._worker_alive(db) is False
    assert await w._decide(db) != "running"


def _seconds(spec: str) -> int:
    """systemd time span like '8h' or '1h30m' -> seconds."""
    import re
    units = {"h": 3600, "m": 60, "s": 1}
    parts = re.findall(r"(\d+)([hms])", spec)
    assert parts and "".join(f"{n}{u}" for n, u in parts) == spec, spec
    return sum(int(n) * units[u] for n, u in parts)


def test_the_systemd_unit_runs_this_module_and_its_timeout_is_the_stale_marker():
    unit = configparser.ConfigParser(strict=False, interpolation=None)
    unit.read(REPO / "deploy" / "wod-casts.service")
    module = unit["Service"]["ExecStart"].rsplit(" -m ", 1)[1].split()[0]
    assert importlib.import_module(module) is w and callable(w.main) and callable(w.run_once)
    assert unit["Service"]["Type"] == "oneshot"
    assert unit["Service"]["MemoryHigh"] == "1.0G" and unit["Service"]["MemoryMax"] == "1.2G"
    assert unit["Unit"]["RequiresMountsFor"] == "/mnt/abyssal-data"       # never runs with the volume absent
    timeout = _seconds(unit["Service"]["TimeoutStartSec"])
    assert R.STARTED_STALE == timedelta(seconds=timeout)                  # P20: a marker is "running" for one unit run
    assert timeout >= R.LOCK_WAIT_S + R.RUN_BUDGET_S + R.PREBAKE_DEADLINE_S + 3600
    timer = configparser.ConfigParser(strict=False, interpolation=None)
    timer.read(REPO / "deploy" / "wod-casts.timer")
    assert timer["Timer"]["Unit"] == "wod-casts.service" and timer["Timer"]["OnCalendar"]
