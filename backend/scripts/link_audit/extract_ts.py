# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Extractors for the TypeScript URL surfaces.

Line-based state machines rather than a TS parser: the constructs are simple
object literals with one URL per line, and a real parser would add a Node
dependency for no accuracy gain. Every extractor ignores `//` comment lines,
because sourceUrl.ts documents dead upstreams in comments (vents-data.
interridge.org, www.oceansites.org) and emitting those as live links would
manufacture failures the product never renders.
"""
from __future__ import annotations

import re

from .models import DeepLinkTemplate, DetailTemplate, LinkRow, UNATTRIBUTED
from .normalize import classify_kind, normalize_url

# `  "isa-contract": {`  or  `  emodnet:               {`
_ENTRY_KEY = re.compile(r'^\s*"?([A-Za-z0-9_-]+)"?:\s*\{')
_URL_FIELD = re.compile(r'\b(?:homepage|url|sourceUrl)\s*:\s*"([^"]+)"')
_BLOCK_END = re.compile(r"^\};")
_ANY_URL = re.compile(r'"(https?://[^"]+)"')


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith(("//", "*", "/*"))


def extract_source_url_ts(text: str, path: str) -> list[LinkRow]:
    """Emit LinkRows for LAYER_SOURCES.homepage and OFFSHORE_SOURCE_HOMEPAGES.url."""
    rows: list[LinkRow] = []
    surface: str | None = None
    key: str | None = None

    for idx, line in enumerate(text.splitlines(), start=1):
        if line.startswith("const OFFSHORE_SOURCE_HOMEPAGES"):
            surface, key = "offshore-homepage", None
            continue
        if line.startswith("const LAYER_SOURCES"):
            surface, key = "layer-source", None
            continue
        if surface and _BLOCK_END.match(line):
            surface, key = None, None
            continue
        if surface is None or _is_comment(line):
            continue

        m_key = _ENTRY_KEY.match(line)
        if m_key:
            key = m_key.group(1)

        m_url = _URL_FIELD.search(line)
        if m_url and key:
            raw = m_url.group(1)
            norm = normalize_url(raw)
            rows.append(LinkRow(
                layer_id=key, surface=surface, url_raw=raw,
                url_normalized=norm, kind=classify_kind(norm),
                file=path, line=idx,
            ))
    return rows


# Matches an implementation `perFeature: (p) => …`, NOT the interface's
# declaration `perFeature?: (p: Properties) => …` (note the required colon
# immediately after the name).
_PERFEATURE_IMPL = re.compile(r"^\s*perFeature:\s*\(", re.M)
_TEMPLATE_LITERAL = re.compile(r"`(https?://[^`]*)`")
_PROP_READ = re.compile(r"\bp\.([A-Za-z_][A-Za-z0-9_]*)")


def extract_deep_link_templates(text: str) -> list[DeepLinkTemplate]:
    """Recover each perFeature builder's URL template and the props it reads.

    Raises ValueError if any perFeature implementation yields no template —
    a missed builder silently shrinks audit coverage, which is the exact
    failure mode this tool exists to prevent.
    """
    impl_count = len(_PERFEATURE_IMPL.findall(text))
    lines = text.splitlines()
    templates: list[DeepLinkTemplate] = []
    key: str | None = None

    for idx, line in enumerate(lines):
        m_key = _ENTRY_KEY.match(line)
        if m_key and not _is_comment(line):
            key = m_key.group(1)
        if not _PERFEATURE_IMPL.match(line) or key is None:
            continue
        # Bound the body at the start of the NEXT registry entry (or the
        # closing "};" of the enclosing Record), not a fixed line count. A
        # fixed window (previously 20 lines) silently reads INTO the next
        # entry whenever a builder body is short, and _PROP_READ has no
        # early stop — so the next builder's `p.<name>` reads get folded
        # into THIS template's props. Task 7 picks the first prop present on
        # a sampled feature, so contaminated props can build a confidently
        # wrong deep link from another layer's schema (verified live:
        # sio-bic ends up with marineregions-eez's `mrgid`; kba ends up with
        # wdpa's `wdpa_id`).
        end = len(lines)
        for j in range(idx + 1, len(lines)):
            if _ENTRY_KEY.match(lines[j]) or _BLOCK_END.match(lines[j]):
                end = j
                break
        body = "\n".join(lines[idx:end])
        m_tpl = _TEMPLATE_LITERAL.search(body)
        if not m_tpl:
            continue
        templates.append(DeepLinkTemplate(
            key=key,
            template=m_tpl.group(1),
            props=tuple(dict.fromkeys(_PROP_READ.findall(body))),
        ))

    if len(templates) != impl_count:
        raise ValueError(
            f"perFeature guard: found {impl_count} implementations but recovered "
            f"{len(templates)} templates. A builder was missed — audit coverage "
            f"would silently shrink."
        )
    return templates


def extract_tooltips(text: str, path: str) -> list[LinkRow]:
    """LAYER_TOOLTIPS_META[<layerId>].sourceUrl (now in controls/tooltips.ts)."""
    rows: list[LinkRow] = []
    key: str | None = None
    inside = False

    for idx, line in enumerate(text.splitlines(), start=1):
        # "export const LAYER_TOOLTIPS_META" in controls/tooltips.ts (moved
        # out of Map3DControls.tsx, gained an export keyword in the split);
        # match both forms rather than assuming module-private.
        if re.match(r"^(export\s+)?const LAYER_TOOLTIPS_META", line):
            inside, key = True, None
            continue
        if inside and _BLOCK_END.match(line):
            break
        if not inside or _is_comment(line):
            continue
        m_key = _ENTRY_KEY.match(line)
        if m_key:
            key = m_key.group(1)
        m_url = re.search(r'\bsourceUrl\s*:\s*"([^"]+)"', line)
        if m_url and key:
            raw = m_url.group(1)
            norm = normalize_url(raw)
            rows.append(LinkRow(
                layer_id=key, surface="tooltip", url_raw=raw,
                url_normalized=norm, kind=classify_kind(norm),
                file=path, line=idx,
            ))
    return rows


# Any string literal: backtick, double- or single-quoted. Matching the *container*
# rather than the URL itself is what makes the nested case correct — line 2978 of
# DetailPanel.tsx is `https://…/search?q=${encodeURIComponent(`${ftype}…`)}`, and a
# bare URL regex either swallows the inner template or stops at an arbitrary
# punctuation character. Here the inner backtick simply closes the outer literal,
# yielding the true static prefix.
_STRING_LITERAL = re.compile(r"`([^`]*)`|\"([^\"]*)\"|'([^']*)'")
_URL_OCCURRENCE = re.compile(r"https?://")
# A URL anywhere inside a literal. Stops at whitespace, any quote (straight or
# curly — the MEMENTO acknowledgement ends `…memento.geomar.de.”`), bracket or
# angle. normalize_url() then strips trailing sentence punctuation.
# `*` not `+`: a bare `"http://"` scheme test must still be RECOVERED so the
# occurrence count balances; _HAS_HOST drops it downstream.
_URL_IN_TEXT = re.compile(r"https?://[^\s\"'`<>)“”‘’]*")
# A scheme alone is not a URL. DetailPanel.tsx:3216 tests
# `sourceUrl.startsWith("http://")`, which the occurrence counter must still see
# (or the guard would mis-count) but which must never be fetched as a citation.
_HAS_HOST = re.compile(r"https?://[^/\s]")

# The site's own origin. `frontend/server.js` ends in a catch-all `app.get('*')`
# that serves the SPA shell for EVERY path, so each of these returns 200 no matter
# what — auditing them manufactures green, not coverage. Excluded loudly (the count
# is reported), never silently dropped.
SELF_HOSTS = ("something-rare.com",)


def _is_self(url: str) -> bool:
    return any(h in url for h in SELF_HOSTS)


def _scan_string_literals(text: str) -> list[tuple[str, int]]:
    """Every http(s) URL inside a TSX/JS string literal, as (raw, line).

    URLs are extracted from WITHIN each literal, not only from literals that
    begin with one: a citation embedded in prose still renders as a link, and
    MEMENTO's required acknowledgement is exactly that — two bare URLs inside a
    quoted sentence.

    Raises ValueError if a URL occurrence on a non-comment line was not recovered
    from some string literal — the same structural guard as the perFeature count
    check, for the same reason: a silently shrunk corpus is this tool's defining
    failure mode. A URL sitting in a JSX text node still trips it, because
    nothing quoted it.
    """
    found: list[tuple[str, int]] = []
    expected = 0

    for idx, line in enumerate(text.splitlines(), start=1):
        if _is_comment(line):
            continue
        expected += len(_URL_OCCURRENCE.findall(line))
        for m in _STRING_LITERAL.finditer(line):
            raw = next(g for g in m.groups() if g is not None)
            for url in _URL_IN_TEXT.findall(raw):
                found.append((url, idx))

    if len(found) != expected:
        raise ValueError(
            f"string-literal guard: {expected} URL occurrences on non-comment "
            f"lines but only {len(found)} recovered from string literals. A URL "
            f"is rendered from a construct this scanner does not read — audit "
            f"coverage would silently shrink."
        )
    return found


def extract_detail_panel(
    text: str, path: str
) -> tuple[list[LinkRow], list[DetailTemplate]]:
    """Split DetailPanel.tsx's URLs into literal citations and `${…}` templates.

    Returns (rows, templates). Literals are fetchable as-is. Templates cannot be
    fetched without substituting a real value, so they are returned separately;
    sample.py decides per template whether a real feature can supply one, and
    falls back to the static prefix when none can.

    Self-origin URLs are dropped here — see SELF_HOSTS.
    """
    rows: list[LinkRow] = []
    templates: list[DetailTemplate] = []

    for raw, line in _scan_string_literals(text):
        if _is_self(raw) or not _HAS_HOST.match(raw):
            continue
        if "${" in raw:
            templates.append(DetailTemplate(
                template=raw,
                prefix=raw.split("${", 1)[0],
                file=path, line=line,
            ))
            continue
        norm = normalize_url(raw)
        rows.append(LinkRow(
            layer_id=UNATTRIBUTED, surface="detail-citation", url_raw=raw,
            url_normalized=norm, kind=classify_kind(norm),
            file=path, line=line,
        ))
    return rows, templates


def extract_seo_tsx(text: str, path: str) -> list[LinkRow]:
    """External citations in SEO.tsx's JSON-LD (url/identifier/sameAs/license).

    Bot-facing, so a rotted link here is what a crawler sees. Self-origin URLs
    are dropped (SELF_HOSTS); everything else is a real outbound citation —
    licence deeds, DOIs, ORCIDs, registry homepages.
    """
    rows: list[LinkRow] = []
    for raw, line in _scan_string_literals(text):
        if _is_self(raw) or not _HAS_HOST.match(raw):
            continue
        norm = normalize_url(raw)
        rows.append(LinkRow(
            layer_id=UNATTRIBUTED, surface="seo-jsonld", url_raw=raw,
            url_normalized=norm, kind=classify_kind(norm),
            file=path, line=line,
        ))
    return rows


def extract_legend_tsx(text: str, path: str) -> list[LinkRow]:
    """Residual hardcoded URLs in LegendPanel.tsx (3 at time of writing).

    LAYER_DOCS no longer exists in TS — content moved to legend.json — so these
    are unattributed leftovers rather than a structured registry.
    """
    rows: list[LinkRow] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if _is_comment(line):
            continue
        for raw in _ANY_URL.findall(line):
            norm = normalize_url(raw)
            rows.append(LinkRow(
                layer_id=UNATTRIBUTED, surface="legend-tsx", url_raw=raw,
                url_normalized=norm, kind=classify_kind(norm),
                file=path, line=idx,
            ))
    return rows
