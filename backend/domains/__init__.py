# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Vertical slices: each module owns one layer family's syncs, endpoints and caches.

`CACHE_CLEARING_DOMAINS` is the registry `/admin/cache/clear` iterates. A domain
that declares a cache global MUST appear here, or its caches are never swept and
the endpoint quietly serves stale data — a failure no test and no gate can see.
`backend/tests/test_domain_cache_clear.py` enforces this.
"""
from . import acoustic, arctic, biodiversity, blog, cables, fields, geo_context, geochem, isa, offshore, onc, seafloor, sensors, seo
from .land import density as land_density
from .land import extractive as land_extractive
from .land import hazards as land_hazards
from .land import arctic as land_arctic

# land_layers is NOT a domains/* submodule (it predates the vertical split and
# lives at backend/land_layers.py). Since the domains/land split it owns no
# cache globals of its own — all 13 land-layer caches moved into
# domains/land/{density,extractive,hazards,arctic}.py, registered below in
# their own right. land_layers stays registered anyway as a harmless
# delegating clear_caches() hook, so both admin sweep sites
# (main.admin_cache_clear, ops_cache_clear) keep working unchanged and a
# future cache added directly to land_layers.py would still be swept.
import land_layers

# domains.land.density (and now domains.land.extractive) are registered in
# their own right (not just reached via land_layers.clear_caches()'s
# delegation) because test_domain_cache_clear's "every module with a cache is
# registered" sweep walks domains/* by real Python package ancestry —
# domains.land.density's/domains.land.extractive's ancestor is domains.land,
# not land_layers, so land_layers being registered does not cover them.
CACHE_CLEARING_DOMAINS = (acoustic, arctic, biodiversity, blog, cables, fields, geo_context, geochem, isa, offshore, onc, seafloor, sensors, seo, land_layers, land_density, land_extractive, land_hazards, land_arctic)
