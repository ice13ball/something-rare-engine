# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Extractors for the two Python URL surfaces."""
from __future__ import annotations

import re

from .models import LinkRow, UNATTRIBUTED
from .normalize import classify_kind, normalize_url

# Any double-quoted string, so a bare `None` in the tuple cannot shift indices.
_QUOTED = re.compile(r'"([^"]*)"')
# Every VectorExport/FieldSource/CompositeExport entry in export_registry.py
# is a dict value of the form `    "some-id": FieldSource(` — the constructor
# itself always takes `id="some-id"` as a KEYWORD arg (never a bare positional
# string right after the open paren), so attribution keys off the dict entry,
# not the constructor call.
_EXPORT_CTOR = re.compile(r'^\s*"([^"]+)":\s*(?:VectorExport|FieldSource|CompositeExport)\(')
_SOURCE_URL_KW = re.compile(r'\bsource_url\s*=\s*"([^"]+)"')


def extract_inventory(text: str, path: str) -> list[LinkRow]:
    """backend/main.py `_INVENTORY` rows: (key, …, source_org, source_url).

    Most tuples fit on one physical line, but at least one real entry
    (`acoustic-stations`, backend/main.py:15509-15512) spans 4 lines. A
    tuple's opening line is accumulated together with however many
    following lines it takes for its parentheses to balance, and the
    quoted-string extraction runs over that reassembled text — never over
    a single physical line. Don't reintroduce the one-tuple-per-line
    assumption; it silently drops multi-line rows instead of erroring.
    """
    rows: list[LinkRow] = []
    inside = False
    lines = text.splitlines()
    idx = 0
    n = len(lines)
    while idx < n:
        line = lines[idx]
        if line.startswith("_INVENTORY"):
            inside = True
            idx += 1
            continue
        if inside and line.startswith("]"):
            break
        stripped = line.strip()
        if not inside or stripped.startswith("#") or not stripped.startswith("("):
            idx += 1
            continue

        # Reassemble the tuple across as many physical lines as it takes
        # for the parens to balance.
        start_line = idx + 1
        buf = [line]
        depth = line.count("(") - line.count(")")
        j = idx
        while depth > 0 and j + 1 < n:
            j += 1
            buf.append(lines[j])
            depth += lines[j].count("(") - lines[j].count(")")
        idx = j + 1

        tuple_text = "\n".join(buf)
        quoted = _QUOTED.findall(tuple_text)
        if len(quoted) < 2:
            continue
        key, raw = quoted[0], quoted[-1]
        if not raw.startswith(("http://", "https://")):
            continue
        norm = normalize_url(raw)
        rows.append(LinkRow(
            layer_id=key, surface="inventory", url_raw=raw,
            url_normalized=norm, kind=classify_kind(norm),
            file=path, line=start_line,
        ))
    return rows


def extract_provenance(text: str, path: str) -> list[LinkRow]:
    """export_registry.py `Provenance(source_url=…)`, attributed to the
    enclosing VectorExport / FieldSource / CompositeExport id."""
    rows: list[LinkRow] = []
    current: str | None = None
    for idx, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("#"):
            continue
        m_ctor = _EXPORT_CTOR.search(line)
        if m_ctor:
            current = m_ctor.group(1)
        m_url = _SOURCE_URL_KW.search(line)
        if m_url:
            raw = m_url.group(1)
            norm = normalize_url(raw)
            rows.append(LinkRow(
                layer_id=current or UNATTRIBUTED, surface="provenance",
                url_raw=raw, url_normalized=norm, kind=classify_kind(norm),
                file=path, line=idx,
            ))
    return rows
