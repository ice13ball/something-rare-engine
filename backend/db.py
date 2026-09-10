# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations
import asyncpg

pool: asyncpg.Pool | None = None

# ⛔ The DSN the pool above was opened with, set by whoever creates the pool.
# A second, independent `os.environ["DATABASE_URL"]` read is NOT the same
# thing: `sensors._connect_for_lock` opens its own connection to hold the
# Argo advisory lock, and an advisory lock only guards writes that happen in
# the SAME database. Two separate env reads can disagree — after an env
# change, or in any process that builds its pool from something other than
# that variable — and then the lock silently guards nothing while both walks
# deadlock, which is the failure it exists to prevent.
dsn: str | None = None
