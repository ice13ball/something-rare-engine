# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The dams map payload must not grow back.

Reported from production 2026-09-11, minutes after the GDW swap: "kółko się
kręci i nic nie działa" — the map hung for tens of seconds after Continue.

⛔ THE WIRE WAS NEVER THE PROBLEM. Measured against production:

    wire (gzip)      1.26 MB      1.97 s
    decoded JSON    16.72 MB      <- the browser parses this on the main thread

41,145 features × 15 properties, most of them null. A null costs as many bytes
as a value: `power_mw` spent 0.78 MB carrying 242 real numbers among 40,903
nulls.

Two fixes, measured on the live database:

    before                       16,715,750 bytes
    json_strip_nulls + 5dp        9,874,539 bytes   (-41%)
    minus the unrendered `quality` field   ~8.9 MB

That puts it level with `seamounts` (10.09 MB decoded), which has always been
fine. ⛔ Stripping nulls is safe ONLY because every panel row sits behind a
presence check and JavaScript treats a missing key and a null key alike
(`undefined != null` is false).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTRACTIVE = ROOT / "backend" / "domains" / "land" / "extractive.py"
PANEL = ROOT / "frontend" / "src" / "components" / "panels" / "land" / "DamPanel.tsx"


def _get_dams_query() -> str:
    """The SQL inside the /dams endpoint — EXECUTABLE lines only.

    ⛔ Both comment syntaxes are stripped, Python `#` as well as SQL `--`.
    The first version of this helper stripped only `--`, so the Python comment
    that explains this very optimisation ("json_strip_nulls — GDW leaves most
    attributes empty…", "ST_AsGeoJSON(geom, 5) — five decimals…") satisfied
    every assertion below. Three sabotages removed the real code and stayed
    green against the prose describing it. That is the fourth guard in this
    session to be fooled by its own explanation.
    """
    src = EXTRACTIVE.read_text()
    start = src.index('@router.get("/dams")')
    end = src.index("FROM dams", start)
    out = []
    for ln in src[start:end].splitlines():
        stripped = ln.strip()
        if stripped.startswith("#"):          # a Python comment is not the query
            continue
        out.append(ln.split("--", 1)[0])      # nor is a SQL comment
    return "\n".join(out)


def test_nulls_are_stripped_from_the_payload():
    q = _get_dams_query()
    assert "json_strip_nulls" in q, (
        "the dams payload sends nulls again — 41,145 features of mostly-empty "
        "attributes is how this endpoint reached 16.72 MB and hung the map"
    )


def test_coordinates_are_not_sent_at_survey_precision():
    q = _get_dams_query()
    m = re.search(r"ST_AsGeoJSON\(geom(?:\s*,\s*(\d+))?\)", q)
    assert m, "the dams geometry is no longer built with ST_AsGeoJSON"
    assert m.group(1) is not None, (
        "ST_AsGeoJSON(geom) with no precision argument emits full double precision; "
        "these are dam centroids, and the extra digits cost megabytes"
    )
    assert int(m.group(1)) <= 6, f"{m.group(1)} decimals is finer than a metre"


def test_the_payload_carries_no_field_the_panel_cannot_show():
    """⛔ Every property costs ~0.8 MB across 41,145 features. A field nobody
    renders is pure parse time. `quality` was exactly that."""
    q = _get_dams_query()
    panel = PANEL.read_text()

    sent = set(re.findall(r"'(\w+)',\s*\w+", q.split("'properties'", 1)[-1]))
    sent.discard("properties")
    # `id` is consumed by SearchBar's featureId(), not by the panel
    ignore = {"id"}

    unused = sorted(
        f for f in sent - ignore
        if f"p.{f}" not in panel
    )
    assert not unused, (
        f"the dams endpoint sends {unused}, which DamPanel never renders. Each "
        "costs roughly 0.8 MB of JSON the browser parses for nothing — either "
        "display it or stop sending it."
    )
