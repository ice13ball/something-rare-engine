# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""One source that never completed a sync must not blank the dates for all of them.

`log_sync_skipped` deliberately leaves `last_synced_at` NULL — a skip that
stamped NOW() would read as freshly synced forever. `/v1/sync/status` then
called `.date()` on that NULL, raised AttributeError, and returned 500 for the
whole map: in production on 2026-09-14 a single row (`sbma-cook-islands`,
"no Landfolio candidate base resolved") removed the "last synced" date from
every layer in the legend's Dates & Freshness tab.

⛔ This is the failure the NULL was introduced to prevent, arriving through the
front door: a source we cannot reach must degrade to "no date known", never to
"no dates at all".
"""
from datetime import datetime, timezone

import pytest

from main import _sync_dates

_WHEN = datetime(2026, 9, 13, 21, 33, tzinfo=timezone.utc)


def test_a_null_date_is_omitted_and_the_others_survive():
    rows = [
        {"source": "argo", "last_synced_at": _WHEN},
        {"source": "sbma-cook-islands", "last_synced_at": None},
        {"source": "contracts", "last_synced_at": _WHEN},
    ]
    out = _sync_dates(rows)

    # ⛔ Positive half first. Without it, a function that returned {} for
    # everything would pass the "the null one is absent" assertion below.
    assert out == {"argo": "2026-09-13", "contracts": "2026-09-13"}
    assert "sbma-cook-islands" not in out


def test_a_table_of_nothing_but_nulls_is_an_empty_map_not_a_crash():
    assert _sync_dates([{"source": "sbma-cook-islands", "last_synced_at": None}]) == {}


def test_the_date_is_the_date_not_the_timestamp():
    # The freshness display shows a day, and a source synced at 23:59 UTC must
    # not appear as the next day just because someone reached for isoformat()
    # on the timestamp.
    out = _sync_dates([{"source": "argo", "last_synced_at": _WHEN}])
    assert out["argo"] == "2026-09-13"
    assert "T" not in out["argo"]
