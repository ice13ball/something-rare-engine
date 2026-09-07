# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Ocean-field layers, split by data family into four sub-modules: `carbon`
(GLODAP / SOCAT / acidification / coral exposure / unified marine carbon),
`habitat` (VME suitability / seabed lithology / CHI), `climatology` (WOA /
oxygen-deox), `currents` (CMEMS surface + 1000 m). A package rather than a
single module, per Task 5 of the backend vertical-split refactor (Phase 3) —
the four families total 43 endpoints / ~1,200+ raw lines, all of it
`services/*.py`-thin route + sync-wrapper code, so navigability drove the
four-way split even though no single family alone would have justified its
own top-level domain module.

`router` aggregates all four sub-routers so `main.py` gains one
`app.include_router(fields.router)` instead of four. `clear_caches()`
aggregates all four sub-modules' `clear_caches()` so `domains/__init__.py`
registers this package once, not its sub-modules individually — see that
module's docstring: "A domain that declares a cache global MUST appear here,
or its caches are never swept". Registering `fields` here (not `fields.carbon`
etc.) is what `backend/tests/test_domain_cache_clear.py` expects, since it
enumerates `domains.__path__` non-recursively (see `_common.py`'s docstring
for why sub-modules can't import each other, and Task 5's report for
confirmation this package is discovered as exactly one entry).

`_common.py` is intentionally NOT imported or re-exported here (only
`from . import carbon, habitat, climatology, currents` below) — it holds a
small intra-package constant (`_HEX_CELLS_SQL`) that three of the four
sub-modules import directly (`from ._common import _HEX_CELLS_SQL`). Importing
it here too would risk a circular import, since this file imports the four
sub-modules that in turn import `_common`.
"""

from __future__ import annotations

from fastapi import APIRouter

from . import carbon, climatology, currents, habitat

router = APIRouter()
router.include_router(carbon.router)
router.include_router(habitat.router)
router.include_router(climatology.router)
router.include_router(currents.router)


def clear_caches() -> None:
    """Drop every field family's cached responses. Called by /admin/cache/clear
    via `domains.CACHE_CLEARING_DOMAINS` (this package is registered there once,
    not its four sub-modules individually)."""
    carbon.clear_caches()
    habitat.clear_caches()
    climatology.clear_caches()
    currents.clear_caches()
