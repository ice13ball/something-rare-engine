# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""IHO S-57 ENC standard code-to-label lookup tables.

These are stable codes published in IHO S-57 Appendix A. Used by any ENC-derived
ingest module (currently NZ LINZ; can extend to future Norway/UK/AU hydrographic
sources if their licensing ever opens).

Each lookup returns a human-readable string for a known integer code, or None
for unknown codes. Callers should preserve the raw integer alongside the
decoded label so source traceability isn't lost.
"""

from __future__ import annotations

# Cable categories — S-57 CATCBL attribute
CATCBL: dict[int, str] = {
    1: "Power line",
    2: "Telephone line",
    3: "Telegraph",
    4: "Fibre-optic cable",
    5: "Submarine cable (general)",
    6: "Bus bar",
}

# Cable status — S-57 STATUS attribute (subset relevant to cables)
STATUS: dict[int, str] = {
    1: "Permanent",
    2: "Occasional",
    3: "Recommended",
    4: "Not recommended",
    5: "Not in use",
    7: "Public",
    11: "Buoyed",
}

# Cable condition — S-57 CONDTN attribute
CONDTN: dict[int, str] = {
    1: "Under construction",
    2: "Ruined",
    3: "Under reclamation",
    5: "Planned construction",
}


def decode_catcbl(raw: int | str | None) -> tuple[str | None, int | None]:
    """Decode CATCBL value. Returns (label, raw_int) or (None, None) on invalid."""
    return _decode(CATCBL, raw)


def decode_status(raw: int | str | None) -> tuple[str | None, int | None]:
    """Decode STATUS value. Returns (label, raw_int) or (None, None) on invalid."""
    return _decode(STATUS, raw)


def decode_condtn(raw: int | str | None) -> tuple[str | None, int | None]:
    """Decode CONDTN value. Returns (label, raw_int) or (None, None) on invalid."""
    return _decode(CONDTN, raw)


def _decode(table: dict[int, str], raw: int | str | None) -> tuple[str | None, int | None]:
    if raw is None or raw == "":
        return None, None
    try:
        code = int(raw)
    except (ValueError, TypeError):
        return None, None
    return table.get(code), code
