# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""One-off: refresh `deepdata_occurrences.depth_m` after the 2026-11 parser fix.

    python -m deepdata_depth_repair            # dry run: walks OBIS, prints counts + examples, writes nothing
    python -m deepdata_depth_repair --apply    # the normal `sync_deepdata` (upsert now refreshes depth_m)

Run on the VPS (not the Mac): the walk downloads the whole ISA node (~201k records).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

import asyncpg
from dotenv import load_dotenv

import db
from domains import biodiversity


async def main(apply: bool) -> None:
    load_dotenv()
    db.pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    try:
        n = await biodiversity.sync_deepdata(dry_run=not apply)
        print(f"{'APPLIED' if apply else 'DRY RUN'}: {n} rows")
    finally:
        await db.pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main("--apply" in sys.argv))
