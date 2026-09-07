#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""One-shot full OBIS deep-sea ingest from the parquet open-data bucket.

Replaces the curated `biodiversity.sync_biodiversity_hotspots` (domains/
biodiversity.py) data set with the unfiltered global deep-sea (depth ≥ 200 m)
occurrences. Run from the VPS in tmux/nohup so it survives abyssal-api
restarts.

Usage on VPS:
    cd <repo checkout>
    tmux new -s obis-ingest
    backend/.venv/bin/python backend/scripts/obis_full_ingest.py
    # detach: Ctrl+b d ; reattach: tmux attach -t obis-ingest

Connects to PostgreSQL via asyncpg (direct, no FastAPI). Uses
`ingestion.obis_parquet._download_batch` to avoid mirroring the full
50 GB bucket — peak temp disk ~350 MB per batch.

Phases:
  1. TRUNCATE biodiversity_hotspots  (clean slate)
  2. List parquet files via DuckDB glob
  3. For each batch of 200 files:
       a. download parallel
       b. DuckDB query: depth ≥ 200 + quality flags
       c. asyncpg COPY-style bulk insert
       d. delete tempdir
  4. VACUUM ANALYZE biodiversity_hotspots
  5. Log final count
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Make sibling `ingestion` importable when running as scripts/foo.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from ingestion.obis_parquet import (  # noqa: E402
    _connect,
    _list_parquet_files,
    _download_batch,
    _WHERE_QUALITY,
)

DATABASE_URL = os.environ["DATABASE_URL"]

FILES_PER_BATCH = 200
INSERT_CHUNK = 5_000

QUERY = f"""
    SELECT
        _id                                          AS obis_id,
        interpreted.scientificName                   AS scientific_name,
        interpreted.phylum                           AS phylum,
        interpreted.class                            AS class_name,
        interpreted."order"                          AS order_name,
        interpreted.family                           AS family,
        interpreted.minimumDepthInMeters             AS depth,
        interpreted.decimalLatitude                  AS lat,
        interpreted.decimalLongitude                 AS lon
      FROM read_parquet(?)
     WHERE {_WHERE_QUALITY}
       AND interpreted.minimumDepthInMeters >= 200
"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("obis_full_ingest")


async def main(start_batch: int = 0, truncate: bool = True):
    overall_t0 = time.time()
    log.info("connecting to PostgreSQL...")
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=4)

    # Phase 1: TRUNCATE (skipped on resume)
    if truncate:
        log.info("PHASE 1: TRUNCATE biodiversity_hotspots")
        async with pool.acquire() as conn:
            await conn.execute("TRUNCATE TABLE biodiversity_hotspots")
            n = await conn.fetchval("SELECT COUNT(*) FROM biodiversity_hotspots")
        log.info("  table cleared (count=%d)", n)
    else:
        async with pool.acquire() as conn:
            n = await conn.fetchval("SELECT COUNT(*) FROM biodiversity_hotspots")
        log.info("PHASE 1: skipped TRUNCATE — resuming with %d existing rows (ON CONFLICT DO NOTHING handles dupes)", n)

    # Phase 2: list files
    log.info("PHASE 2: list parquet files via DuckDB glob")
    duck = _connect()
    files = _list_parquet_files(duck)
    log.info("  %d files in OBIS open-data bucket", len(files))

    # Phase 3: batched ingest
    total_batches = (len(files) + FILES_PER_BATCH - 1) // FILES_PER_BATCH
    skip_to = start_batch * FILES_PER_BATCH
    if start_batch > 0:
        log.info("PHASE 3: resuming from batch %d/%d (skipping files 0–%d)", start_batch + 1, total_batches, skip_to)
    else:
        log.info("PHASE 3: ingest %d batches × %d files", total_batches, FILES_PER_BATCH)
    total_inserted = 0
    total_yielded = 0
    last_log = time.time()

    for batch_idx, i in enumerate(range(0, len(files), FILES_PER_BATCH)):
        if batch_idx < start_batch:
            continue
        batch_s3 = files[i : i + FILES_PER_BATCH]
        batch_dir = tempfile.mkdtemp(prefix="obis-batch-")
        try:
            t0 = time.time()
            local = _download_batch(batch_s3, batch_dir, parallel=12)
            dl_t = time.time() - t0
            if not local:
                log.warning("batch %d: 0 files downloaded — skip", batch_idx)
                continue

            t0 = time.time()
            cur = duck.execute(QUERY, [local])
            rows_in_batch = 0
            async with pool.acquire() as conn:
                while True:
                    rows = cur.fetchmany(INSERT_CHUNK)
                    if not rows:
                        break
                    rows_in_batch += len(rows)
                    payload = []
                    for row in rows:
                        obis_id, name, phylum, cls, ordr, fam, depth, lat, lon = row
                        if not obis_id or lat is None or lon is None:
                            continue
                        payload.append((obis_id, name, phylum, cls, ordr, fam, depth, float(lon), float(lat)))
                    if payload:
                        await conn.executemany(
                            """INSERT INTO biodiversity_hotspots
                                   (obis_id, scientific_name, phylum, class_name, order_name,
                                    family, depth, geom)
                               VALUES ($1, $2, $3, $4, $5, $6, $7,
                                   ST_SetSRID(ST_MakePoint($8, $9), 4326))
                               ON CONFLICT (obis_id) DO NOTHING""",
                            payload,
                        )
                        total_inserted += len(payload)
            ins_t = time.time() - t0
            total_yielded += rows_in_batch

            now = time.time()
            if now - last_log >= 30 or batch_idx < 5:
                log.info(
                    "batch %d/%d (files %d–%d): yielded=%d insert=%d (running total=%d) | dl %.1fs ins %.1fs",
                    batch_idx + 1,
                    (len(files) + FILES_PER_BATCH - 1) // FILES_PER_BATCH,
                    i,
                    i + len(batch_s3),
                    rows_in_batch,
                    len(payload) if payload else 0,
                    total_inserted,
                    dl_t,
                    ins_t,
                )
                last_log = now
        except Exception:
            log.exception("batch %d failed — continuing", batch_idx)
        finally:
            shutil.rmtree(batch_dir, ignore_errors=True)

    log.info("PHASE 3 done: yielded=%d, inserted=%d (after CONFLICT dedup)", total_yielded, total_inserted)

    # Phase 4: VACUUM ANALYZE
    log.info("PHASE 4: VACUUM ANALYZE biodiversity_hotspots")
    async with pool.acquire() as conn:
        await conn.execute("VACUUM ANALYZE biodiversity_hotspots")
        final = await conn.fetchval("SELECT COUNT(*) FROM biodiversity_hotspots")
        n_species = await conn.fetchval(
            "SELECT COUNT(DISTINCT scientific_name) FROM biodiversity_hotspots"
        )
    log.info("FINAL: %d rows / %d distinct species (overall %.1f min)",
             final, n_species, (time.time() - overall_t0) / 60)
    await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OBIS Open Data full deep-sea ingest.")
    parser.add_argument("--start-batch", type=int, default=0, help="0-indexed batch to resume from (default 0)")
    parser.add_argument("--no-truncate", action="store_true", help="skip Phase 1 TRUNCATE (use when resuming)")
    args = parser.parse_args()
    asyncio.run(main(start_batch=args.start_batch, truncate=not args.no_truncate))
