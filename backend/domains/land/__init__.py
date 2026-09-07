# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Land-layer domain package — step 1 of splitting `land_layers.py` (3,341
lines, the only backend file the 2026-08-07/08 vertical split never
touched). This first step moves only the genuinely cross-family shared
leaves into `common.py`; no layer family has been split out yet, so this
package exposes no router and is not yet registered in `domains/__init__.py`
CACHE_CLEARING_DOMAINS — `land_layers.py` itself still owns all caches and
the router.
"""

from __future__ import annotations
