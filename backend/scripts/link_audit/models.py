# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Data types for the source-link audit.

A LinkRow is one *occurrence* of a URL. The same URL appears many times across
surfaces (glodap.info is in tooltips, provenance and the inventory); each
occurrence is its own row so a report can name every place a dead link renders.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

# Where in the product this link renders.
SURFACES = (
    "layer-source",       # sourceUrl.ts LAYER_SOURCES[k].homepage
    "offshore-homepage",  # sourceUrl.ts OFFSHORE_SOURCE_HOMEPAGES[k].url
    "tooltip",            # Map3DControls.tsx LAYER_TOOLTIPS_META[id].sourceUrl
    "legend-locale",      # locales/<loc>/legend.json
    "inventory",          # backend/main.py _INVENTORY
    "provenance",         # backend/services/export_registry.py
    "legend-tsx",         # residual hardcoded URLs in LegendPanel.tsx
    "deep-link",          # built from a sampled feature via perFeature
    "stored",             # a URL stored in a Postgres row, seen via the API
    "detail-citation",    # DetailPanel.tsx literal citation (no ${})
    "detail-prefix",      # DetailPanel.tsx template, checked at its static prefix
    "detail-deep-link",   # DetailPanel.tsx template, built from a sampled feature
    "seo-jsonld",         # SEO.tsx JSON-LD url/identifier/sameAs/license
)

KINDS = ("homepage", "doi", "endpoint", "deep-link")

VERDICTS = (
    "OK", "REDIRECT_OK", "RATE_LIMITED", "BLOCKED",
    "DEAD", "CHANGED_MEANING", "NOT_CHECKED",
)

UNATTRIBUTED = "(unattributed)"


@dataclass(frozen=True)
class LinkRow:
    layer_id: str
    surface: str
    url_raw: str
    url_normalized: str
    kind: str
    file: str
    line: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DeepLinkTemplate:
    """A perFeature builder recovered from sourceUrl.ts."""
    key: str
    template: str          # e.g. "https://obis.org/occurrence/${id}"
    props: tuple[str, ...] # feature property names the builder reads


@dataclass(frozen=True)
class DetailTemplate:
    """A `${…}`-bearing URL literal recovered from DetailPanel.tsx.

    Distinct from DeepLinkTemplate: a perFeature builder lives in a Record keyed
    by layer id, so the sampler knows which endpoint supplies its ids. These are
    inlined in JSX and their placeholders are *local variables* (`slug`, `wdpaId`,
    `locationCode`), which name nothing the API returns. Mapping one to a real
    feature property is therefore a hand-verified act — see DETAIL_TEMPLATE_LAYERS
    in sample.py. Unmapped templates are still checked at `prefix`.
    """
    template: str          # e.g. "https://www.protectedplanet.net/${wdpaId}"
    prefix: str            # everything before the first "${" — always fetchable
    file: str
    line: int


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int | None      # None when the request never completed
    final_url: str | None
    title: str | None
    error: str | None
