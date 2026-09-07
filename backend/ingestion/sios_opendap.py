# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
sios_opendap.py — Pure OPeNDAP DDS/ASCII parser for SIOS Svalbard time-series.

No network calls, no DB. Stdlib only. Consumed by _sync_sios (Task 2+).
"""
from __future__ import annotations
import re
import math

_EPOCH_1900_OFFSET_DAYS = 25567  # days from 1900-01-01 to 1970-01-01
_FILL = 1e30


def parse_data_variable(dds_text: str) -> str | None:
    """Return first Grid/Array variable name that isn't 'time'."""
    for m in re.finditer(r'(?:Float64|Float32|Int32|Int16|Byte)\s+(\w+)\[', dds_text):
        if m.group(1) != "time":
            return m.group(1)
    return None


def time_dim_size(dds_text: str) -> int | None:
    """Return the size of the time dimension from DDS text."""
    m = re.search(r'time\s*=\s*(\d+)', dds_text)
    return int(m.group(1)) if m else None


def epoch_ms_from_days_since_1900(v: float) -> int:
    """Convert 'days since 1900-01-01' float to epoch milliseconds."""
    return int(round((v - _EPOCH_1900_OFFSET_DAYS) * 86400000.0))


def _floats(line: str) -> list[float]:
    """Parse comma-separated floats from an OPeNDAP ASCII data row (skip label token)."""
    out = []
    for tok in line.split(",")[1:]:  # first token is the var label e.g. "shrtRad.time"
        tok = tok.strip()
        try:
            out.append(float(tok))
        except ValueError:
            out.append(math.nan)
    return out


def parse_ascii_grid(ascii_text: str, var: str) -> list[tuple[float, float]]:
    """
    Extract (time_value, data_value) pairs from OPeNDAP ASCII response.

    Looks for rows starting with '{var}.time' and '{var}.{var}', zips them,
    and filters out non-finite values and fill-value sentinels (≥1e30).
    """
    tline = vline = None
    for ln in ascii_text.splitlines():
        s = ln.strip()
        if s.startswith(f"{var}.time"):
            tline = s
        elif s.startswith(f"{var}.{var}"):
            vline = s
    if not tline or not vline:
        return []
    times, vals = _floats(tline), _floats(vline)
    pairs = []
    for t, v in zip(times, vals):
        if not (math.isfinite(t) and math.isfinite(v)):
            continue
        if abs(v) >= _FILL:
            continue
        pairs.append((t, v))
    return pairs


def build_series(dds_text: str, ascii_text: str) -> dict | None:
    """
    Parse DDS + ASCII text into a downsampled time series dict.

    Returns: {"var": str, "points": [[epoch_ms: int, val: float], ...]} sorted by time,
    or None if unparseable.
    """
    var = parse_data_variable(dds_text)
    if not var:
        return None
    pairs = parse_ascii_grid(ascii_text, var)
    if not pairs:
        return None
    pts = sorted([epoch_ms_from_days_since_1900(t), float(v)] for t, v in pairs)
    return {"var": var, "points": pts}
