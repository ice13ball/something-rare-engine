# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Disk limits for the DuckDB spill files of the syncs: a cap per connection, a free-space gate before a run.

DuckDB's `temp_directory` has no upper bound by default ("the available disk space on the drive"), so a
query that spills can fill the data disk the production database, the WOD downloads and the plankton model
share. Two guards, both here so the four connections (OBIS, GLODAP, plankton extract, plankton load) behave
alike:

1. `apply_temp_limit(con, ENV_VAR, default)` -> `SET max_temp_directory_size`. When the cap is hit DuckDB
   raises `OutOfMemoryException` ("failed to offload data block ... This limit was set by the
   'max_temp_directory_size' setting", measured on 1.5.2); `is_temp_limit_error` recognises exactly that and
   not an ordinary memory_limit OOM (whose message never names the setting).
2. `free_space_shortfall(path, need)` -> a human reason when the filesystem cannot hold a worst-case run,
   BEFORE anything is downloaded.

Where each number comes from is written next to it.
"""
from __future__ import annotations

import logging
import os
import re
import shutil

log = logging.getLogger(__name__)

# ── Defaults (DuckDB size strings). Each is overridable by an environment variable of the same name. ──
# Measured 2026-11-06 with the production settings of each connection (DuckDB 1.5.2), polling the temp dir
# and duckdb_temporary_files() every 0.2 s. A cap is the measured peak with room for the source to grow;
# where the peak was 0 the cap only has to stop a changed plan from eating the disk.
# OBIS batch query, memory_limit 3GB, the 77,013 curated names of production: peak 0 B on the largest file
# (5422689c, 20.4 GB, full scan, 0 rows kept) and on NOAA DSCRTP (f5a4799e, 1,499,010 rows kept). The plan
# streams (filter + semi-join against the small curated table); the cap is about the memory limit.
OBIS_DUCKDB_TEMP_MAX = "4GiB"
# GLODAPv3 ORDER BY, memory_limit 700MB, CSV 1.03 GB / 1,498,120 rows: peak 0.39–0.48 GB on disk over three runs.
GLODAP_DUCKDB_TEMP_MAX = "2GiB"
# Plankton extract child, memory_limit 700MB: peak 0 B on the two largest plankton datasets (Australian
# Microbiome b508f7bc, 5.0 GB, 5,139,769 rows extracted; iNaturalist eaea291a, 5.1 GB). Per CHILD: up to
# PLANKTON_PARALLEL children share one temp dir.
PLANKTON_EXTRACT_DUCKDB_TEMP_MAX = "1GiB"
# Plankton load, memory_limit 256MB: peak 0 B on the same two extracts (28 MB and 0.2 MB).
PLANKTON_LOAD_DUCKDB_TEMP_MAX = "1GiB"

# Space other than the spill that a run needs on the same filesystem.
# One batch of 12 OBIS parquet files in obis-batch-*, for the gate BEFORE the run (S3 listing 2026-11-06:
# median batch 20 MB, p99 2.06 GiB, max 19.1 GiB). Each batch is ALSO gated on its real size (HEAD) in
# obis_parquet._batch_space_shortfall; this reserve is used there only when a HEAD fails.
OBIS_BATCH_RESERVE = "3GiB"
# GLODAP zip (~120 MB) + the unpacked CSV (1.03 GB), both on disk while unpacking.
GLODAP_CSV_RESERVE = "2GiB"
# Extracted parquet files waiting for the load: the largest dataset's extract was 28 MB.
PLANKTON_EXTRACT_RESERVE = "1GiB"
# Slack on top of every gate.
SCRATCH_MARGIN = "1GiB"

# DuckDB reads KB/MB/GB/TB as powers of 1000 and KiB/MiB/GiB/TiB as powers of 1024 (checked on 1.5.2:
# '1GB' -> 953.6 MiB, '1GiB' -> 1.0 GiB).
_UNITS = {
    "b": 1,
    "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4,
    "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4,
}
_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([A-Za-z]+)\s*$")
_MIN_BYTES = 1024 ** 2          # a cap under 1 MiB is a typo, not a policy


class ScratchLimitExceeded(RuntimeError):
    """A DuckDB spill hit its `max_temp_directory_size`: the run must end without swapping or purging."""


def parse_size(text: str) -> int:
    """'8GiB' -> bytes. ValueError for anything that is not <number><B|KB|MB|GB|TB|KiB|MiB|GiB|TiB>."""
    m = _SIZE_RE.match(text) if isinstance(text, str) else None
    if not m or m.group(2).lower() not in _UNITS:
        raise ValueError(f"not a size: {str(text)[:40]!r}")
    return int(float(m.group(1)) * _UNITS[m.group(2).lower()])


def env_bytes(env_var: str, default: str) -> int:
    """The size in `env_var` (or `default`) in bytes. Garbage or < 1 MiB in the environment logs a warning
    and falls back to `default`; the default itself is code and must parse."""
    raw = os.getenv(env_var)
    if raw is not None and raw.strip():
        try:
            value = parse_size(raw)
            if value >= _MIN_BYTES:
                return value
            raise ValueError("below 1 MiB")
        except ValueError as e:
            log.warning("%s=%r rejected (%s) — using the default %s", env_var, raw[:40], e, default)
    return parse_size(default)


def apply_temp_limit(con, env_var: str, default: str) -> int:
    """SET max_temp_directory_size on `con` from `env_var` (fallback `default`). Returns the cap in bytes.
    Only an integer byte count we computed reaches the SQL, never the environment text."""
    cap = env_bytes(env_var, default)
    con.execute(f"SET max_temp_directory_size='{int(cap)}B'")
    return cap


def is_temp_limit_error(exc: BaseException) -> bool:
    """True only for DuckDB's "the spill directory is full" error: an OutOfMemoryException whose message
    names `max_temp_directory_size`. An ordinary memory_limit OOM ("failed to pin block ...") is not one."""
    return type(exc).__name__ == "OutOfMemoryException" and "max_temp_directory_size" in str(exc)


def _nearest_existing(path) -> str:
    p = os.path.abspath(os.fspath(path))
    while not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


def _mib(n: int) -> int:
    return n >> 20


def free_space_shortfall(path, need_bytes: int, breakdown: str = "") -> str | None:
    """None when the filesystem holding `path` (its nearest existing ancestor) has `need_bytes` free,
    else a reason in the style of wod_casts.py's DOWNLOAD_HEADROOM check. `breakdown` is the parenthesised
    part, e.g. 'temp cap 8192 MiB + batch 8192 MiB + margin 1024 MiB'."""
    free = shutil.disk_usage(_nearest_existing(path)).free
    if free >= need_bytes:
        return None
    why = f" ({breakdown})" if breakdown else ""
    return f"disk: {path} has {_mib(free)} MiB free, needs {_mib(need_bytes)} MiB{why}"
