# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Re-ask GBIF for the species the old IUCN backfill stored as 'DD' without an answer.

    python -m scripts.recheck_iucn_dd [--batch-size 200]            # dry run, writes nothing
    python -m scripts.recheck_iucn_dd --apply [--batch-size 200]    # bounded batch; repeat until looked_up is 0

See `domains.biodiversity.recheck_dd_iucn_categories`. Run on the VPS under nice/ionice; it needs
~2 GBIF requests per species and sleeps 0.3 s between species.
"""
import argparse
import asyncio
import json
import os
import sys

import asyncpg
from dotenv import load_dotenv

import db
from domains import biodiversity


async def _run(batch_size: int, apply: bool) -> dict:
    db.pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    try:
        return await biodiversity.recheck_dd_iucn_categories(batch_size=batch_size, dry_run=not apply)
    finally:
        await db.pool.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--batch-size", type=int, default=200)
    ap.add_argument("--apply", action="store_true", help="write; without it nothing is written")
    args = ap.parse_args()
    load_dotenv()
    print(json.dumps(asyncio.run(_run(args.batch_size, args.apply)), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
