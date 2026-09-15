# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Extract URLs from the per-locale legend.json files and compare across locales.

The same source URL is duplicated into every locale file. A fix applied to `en`
alone leaves the other locales citing a stale resource while still returning
HTTP 200 — a defect no link checker can see, so it gets its own static check.
"""
from __future__ import annotations

import re
from typing import Any

from .models import UNATTRIBUTED, LinkRow
from .normalize import classify_kind, normalize_url

# Stops at whitespace, quote, angle bracket (i18n <1> markers) and closing paren.
_URL_IN_PROSE = re.compile(r"https?://[^\s\"'<>)\\]+")


def _walk_strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _walk_strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _walk_strings(v)]
    return []


def _rows_for(layer_id: str, block: Any, path: str) -> list[LinkRow]:
    rows: list[LinkRow] = []
    for text in _walk_strings(block):
        for raw in _URL_IN_PROSE.findall(text):
            norm = normalize_url(raw)
            rows.append(LinkRow(
                layer_id=layer_id, surface="legend-locale", url_raw=raw,
                url_normalized=norm, kind=classify_kind(norm),
                file=path, line=0,  # JSON: no meaningful line without a re-parse
            ))
    return rows


def extract_locale_urls(payload: dict, locale: str, path: str) -> list[LinkRow]:
    """Walk the ENTIRE legend.json payload, not just `layers`.

    URLs found under `layers.<layerId>.…` are attributed to that layer id
    (unchanged behaviour). Every other URL in the file — `verify`, `dates`,
    `inventory`, `footer`, or any other top-level section — is real audit
    surface too, but can't be confidently tied to one layer, so it is
    attributed to the explicit `UNATTRIBUTED` bucket rather than being
    silently dropped.
    """
    rows: list[LinkRow] = []
    for layer_id, block in (payload.get("layers") or {}).items():
        rows.extend(_rows_for(layer_id, block, path))
    for key, block in payload.items():
        if key == "layers":
            continue
        rows.extend(_rows_for(UNATTRIBUTED, block, path))
    return rows


def find_locale_divergence(by_locale: dict[str, list[LinkRow]]) -> list[dict]:
    """Compare every locale's URL set against `en`, per layer."""
    def index(rows: list[LinkRow]) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for r in rows:
            out.setdefault(r.layer_id, set()).add(r.url_normalized)
        return out

    baseline = index(by_locale.get("en", []))
    findings: list[dict] = []
    for locale, rows in by_locale.items():
        if locale == "en":
            continue
        other = index(rows)
        for layer_id, expected in baseline.items():
            got = other.get(layer_id, set())
            missing, extra = sorted(expected - got), sorted(got - expected)
            if missing or extra:
                findings.append({
                    "layer_id": layer_id, "locale": locale,
                    "missing": missing, "extra": extra,
                })
    return findings


def extract_site_graph(payload: Any, path: str) -> list[LinkRow]:
    """Every external URL in the JSON-LD graph served to crawlers.

    ⛔ Never audited before 2026-09-15. `seo/site-graph.json` is the document
    Google and Scholar read: it carries the platform's DOI, the companion
    documentation record's DOI, the author ORCID and the licence deeds. A dead
    URL here is a dead citation in the structured data, and the extractor named
    `seo-jsonld` did not reach it — it scanned SEO.tsx's own literals, while
    the graph arrives via an import.
    """
    rows: list[LinkRow] = []
    for text in _walk_strings(payload):
        for raw in _URL_IN_PROSE.findall(text):
            norm = normalize_url(raw)
            rows.append(LinkRow(
                layer_id=UNATTRIBUTED, surface="citation", url_raw=raw,
                url_normalized=norm, kind=classify_kind(norm),
                file=path, line=0,  # JSON: no meaningful line without a re-parse
            ))
    return rows
