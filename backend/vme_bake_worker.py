# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Standalone, memory/CPU-isolated VME bake worker.

Runs as its OWN systemd unit (vme-bake.service, cgroup-capped) — never inside abyssal-api.
Triggered every few minutes by vme-bake.timer; only bakes when the control flag is set
(admin Force Sync) or the surface is stale (>30 days). Serializes against obis-sync on a
Postgres advisory lock so the two heavy jobs never peak together.
"""
from __future__ import annotations
import asyncio, logging, os
import asyncpg
from dotenv import load_dotenv
import db
from services import vme_sdm

LOCK_KEY = 4242001            # shared with obis_sync_worker
STALE_DAYS = 30
MIN_AVAIL_KIB = 3 * 1024 * 1024  # 3 GiB
log = logging.getLogger("vme_bake_worker")


def _mem_available_kib():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


async def _should_bake(conn):
    forced = await conn.fetchval("SELECT force_requested FROM vme_bake_control WHERE id")
    if forced:
        return True
    last = await conn.fetchval("SELECT last_synced_at FROM sync_log WHERE source='vme-sdm'")
    if last is None:
        return True
    from datetime import datetime, timezone, timedelta
    return (datetime.now(timezone.utc) - last) > timedelta(days=STALE_DAYS)


async def main():
    load_dotenv()
    avail = _mem_available_kib()
    if avail is not None and avail < MIN_AVAIL_KIB:
        log.warning("vme-bake: MemAvailable %d KiB < 3 GiB — deferring", avail)
        return
    db.pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=3)
    try:
        # Hold ONE connection for the whole critical section: session-level advisory
        # locks are scoped to their connection, and asyncpg releases them
        # (pg_advisory_unlock_all) the moment a pooled connection is returned. So the
        # lock MUST stay on lock_conn across the entire bake, not be acquired-then-released.
        async with db.pool.acquire() as lock_conn:
            if not await _should_bake(lock_conn):
                log.info("vme-bake: nothing to do (fresh, no force)")
                return
            got = await lock_conn.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY)
            if not got:
                log.info("vme-bake: advisory lock held (obis likely syncing) — deferring")
                return
            try:
                log.info("vme-bake: starting bake")
                result = await vme_sdm.bake_vme(db.pool)
                log.info("vme-bake: done %s", result)
                await lock_conn.execute("UPDATE vme_bake_control SET force_requested=FALSE WHERE id")
                await lock_conn.execute(
                    """INSERT INTO sync_log (source, last_synced_at, records_added, total_records)
                       VALUES ('vme-sdm', now(), $1, $1)
                       ON CONFLICT (source) DO UPDATE SET last_synced_at=now(),
                         records_added=EXCLUDED.records_added, total_records=EXCLUDED.total_records""",
                    int(result.get("cells", 0)))
            finally:
                await lock_conn.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
    finally:
        await db.pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
