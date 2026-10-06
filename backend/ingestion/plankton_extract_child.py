# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Child-process entry: extract ONE OBIS dataset, print one JSON line, exit.

    python -m ingestion.plankton_extract_child        # request as JSON on stdin

stdin  {"source": <url|path>, "dest": <path>, "scratch": <dir>, "title": <str|null>}
stdout last line: {"rows": n, "peak_rss_mb": m}            exit 0
                  {"error": "<ExceptionType>"}              exit 1   (type only: messages can carry URLs)

Why a process per dataset: DuckDB's memory_limit bounds only its buffer manager, not the httpfs /
parquet-metadata caches, Arrow results or glibc fragmentation; in ONE long-lived process they
accumulated to ~1.2 GB over ~1,700 datasets. A process that exits gives all of it back.
Imports only plankton_extract (no schema, no asyncpg, no logging setup, no db pool).
"""
from __future__ import annotations

import json
import os
import pathlib
import resource
import sys
import threading
import time


def _peak_rss_mb() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss      # KiB on Linux, bytes on macOS
    return int(peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024)


def _exit_with_parent() -> None:
    """A parent that is SIGKILLed / SIGTERMed leaves no finally block behind: without this the child
    would run on, orphaned, for up to the whole timeout inside the cgroup."""
    parent = os.getppid()

    def watch():
        while True:
            time.sleep(3)
            if os.getppid() != parent:
                os._exit(3)
    threading.Thread(target=watch, daemon=True).start()


def main() -> int:
    req = json.load(sys.stdin)
    _exit_with_parent()
    try:
        from ingestion.plankton_extract import connect_duckdb, extract_dataset
        con = connect_duckdb(pathlib.Path(req["scratch"]))
        try:
            rows = extract_dataset(con, req["source"], pathlib.Path(req["dest"]), title=req.get("title"))
        finally:
            con.close()
    except BaseException as e:           # noqa: BLE001 — the parent turns any failure into "dataset failed"
        print(json.dumps({"error": type(e).__name__}))
        return 1
    print(json.dumps({"rows": rows, "peak_rss_mb": _peak_rss_mb()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
