# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Guard: SEO species counts must fall back to a live join when the cache is empty.

`backend/main.py` cannot be imported here (heavy optional deps) and there is no
DATABASE_URL in CI, so this is a source-level structural check — the only way to
pin the property without a live DB. The failure it guards against is a public,
bot-indexed page silently reporting "0 deep-sea species" because
claim_species_cache happens to be unbuilt. That regression would pass every
row-count smoke test.

Source moved from `main.py` to `domains/seo.py` in Task 1 of the backend
vertical-split refactor, Phase 3 (all `/v1/seo/*` endpoints + their helpers).
`_seo_env_counts` lost its leading underscore in the move (top-level function
rename rule — see `domains/seo.py`'s docstring); `_SEO_ENV_COUNTS_SQL`/
`_SEO_ENV_COUNTS_LIVE_SQL` are constants and kept theirs.
"""
from __future__ import annotations

import pathlib

_SRC = (pathlib.Path(__file__).resolve().parents[1] / "domains" / "seo.py").read_text(encoding="utf-8")


def _live_sql_literal() -> str:
    """The triple-quoted body of the _SEO_ENV_COUNTS_LIVE_SQL constant only."""
    marker = '_SEO_ENV_COUNTS_LIVE_SQL = """'
    start = _SRC.index(marker) + len(marker)
    end = _SRC.index('"""', start)
    return _SRC[start:end]


def test_live_fallback_sql_exists_and_is_a_real_spatial_join():
    assert "_SEO_ENV_COUNTS_LIVE_SQL" in _SRC
    sql = _live_sql_literal()
    # It must hit the actual occurrence table, not the cache …
    assert "biodiversity_hotspots" in sql
    assert "claim_species_cache" not in sql
    # … at the canonical 10 km radius (10000 m geography clause).
    assert "10000" in sql


def test_env_counts_chooses_live_when_cache_empty():
    idx = _SRC.index("async def seo_env_counts")
    body = _SRC[idx: idx + 900]
    # Detects miss by GLOBAL emptiness (0 is a legitimate per-page answer, so it
    # must NOT be used as the miss signal) …
    assert "EXISTS(SELECT 1 FROM claim_species_cache)" in body
    # … and switches to the live SQL on the empty branch.
    assert "_SEO_ENV_COUNTS_LIVE_SQL" in body


def test_both_seo_handlers_go_through_the_helper():
    # Neither handler may call the raw cache SQL directly (that bypasses fallback).
    assert 'seo_env_counts(conn, "resource_type"' in _SRC
    assert 'seo_env_counts(conn, "contractor_name"' in _SRC
    assert "_SEO_ENV_COUNTS_SQL.format(" not in _SRC  # only the helper picks the SQL
