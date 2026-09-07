# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from __future__ import annotations

import threading
from datetime import datetime


class QuotaTracker:
    """In-memory fixed-window per-key request counters (minute + day).

    Correct only under a single process/worker. Counters reset on restart.
    """

    def __init__(self) -> None:
        self._minute: dict[int, list[int]] = {}  # key_id -> [bucket, count]
        self._day: dict[int, list[int]] = {}
        self._lock = threading.Lock()

    def check_and_count(self, key_id: int, per_min: int | None,
                        per_day: int | None, now: datetime) -> bool:
        """Return True (and record the hit) if within limits; False if over.

        Fixed UTC windows (caller passes timezone-aware UTC `now`): minute = ts//60,
        day = ts//86400. Per-key entries are overwritten in place each window (not
        accumulated); the dicts only grow with the number of distinct keys, which is
        small (one row per member key), so no eviction/GC is needed.
        """
        ts = now.timestamp()
        m_bucket = int(ts // 60)
        d_bucket = int(ts // 86400)
        with self._lock:
            if per_min is not None:
                cur = self._minute.get(key_id)
                if cur is None or cur[0] != m_bucket:
                    cur = [m_bucket, 0]
                    self._minute[key_id] = cur
                if cur[1] >= per_min:
                    return False
            if per_day is not None:
                curd = self._day.get(key_id)
                if curd is None or curd[0] != d_bucket:
                    curd = [d_bucket, 0]
                    self._day[key_id] = curd
                if curd[1] >= per_day:
                    return False
            if per_min is not None:
                self._minute[key_id][1] += 1
            if per_day is not None:
                self._day[key_id][1] += 1
            return True


# module-global tracker used by resolve_and_check
_quota = QuotaTracker()
