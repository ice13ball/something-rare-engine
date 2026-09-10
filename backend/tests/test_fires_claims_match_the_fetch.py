# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""We may not promise a sensor we never ask NASA for.

`_FIRMS_SENSORS` has held three VIIRS entries and no MODIS for as long as the
layer has existed. Fourteen user-facing strings said otherwise — legend
description, limitations, source, reading, the Dates and Verify tabs, the
left-menu tooltip in four locales, the backend inventory row, the Area Export
provenance, the layer type description, sourceUrl's attribution, and the legal
page. Measured on production 2026-09-10:

    VIIRS_SNPP   99,331      MODIS   0
    VIIRS_NOAA20 98,622
    VIIRS_NOAA21 96,390      <- fetched, and named in none of those strings

So the copy claimed a 1 km instrument that contributes nothing, and omitted a
satellite that contributes a third of the rows.

⛔ This test derives the sensor list from the CODE. Hardcoding "no MODIS" would
go stale the day someone adds a MODIS feed, and would then forbid a true claim.
"""
import ast
import json
import pathlib
import re

ROOT    = pathlib.Path(__file__).resolve().parents[2]
HAZARDS = ROOT / "backend" / "domains" / "land" / "hazards.py"
LOCALES = ROOT / "frontend" / "public" / "locales"

#: Files that carry user-facing prose about this layer. Each was found holding
#: the MODIS claim on 2026-09-10; a new one must be added here deliberately.
PROSE_FILES = [
    ROOT / "backend" / "main.py",
    ROOT / "backend" / "services" / "export_registry.py",
    ROOT / "frontend" / "src" / "types" / "landLayers.ts",
    ROOT / "frontend" / "src" / "utils" / "sourceUrl.ts",
    ROOT / "frontend" / "src" / "utils" / "exportLayers.ts",
    ROOT / "frontend" / "src" / "content" / "legalContent.ts",
]

#: Instrument families a fire product could plausibly be attributed to.
KNOWN_SENSOR_WORDS = {"MODIS", "VIIRS"}


def _sensors_we_fetch() -> set[str]:
    tree = ast.parse(HAZARDS.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_FIRMS_SENSORS" for t in node.targets):
            return {s.split("_")[0].upper() for s in ast.literal_eval(node.value)}
    return set()


def _satellites_we_fetch() -> set[str]:
    tree = ast.parse(HAZARDS.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "_FIRMS_SENSORS" for t in node.targets):
            out = set()
            for s in ast.literal_eval(node.value):
                parts = s.replace("_NRT", "").split("_", 1)
                if len(parts) == 2:
                    out.add(parts[1].upper())
            return out
    return set()


def _locale_prose() -> dict:
    out = {}
    for loc in sorted(p for p in LOCALES.iterdir() if p.is_dir()):
        blob = []
        for fname, keys in (("legend.json", ("layers", "dates", "verify")),
                            ("panels.json", ("tooltip", "fire"))):
            f = loc / fname
            if not f.is_file():
                continue
            d = json.loads(f.read_text(encoding="utf-8"))

            def walk(o):
                if isinstance(o, dict):
                    for v in o.values():
                        walk(v)
                elif isinstance(o, str) and ("fire" in o.lower() or "FIRMS" in o
                                             or "Brand" in o or "incend" in o
                                             or "pożar" in o.lower()):
                    blob.append(o)
            for k in keys:
                walk(d.get(k, {}))
        out[loc.name] = "\n".join(blob)
    return out


def test_the_fixture_reads_a_real_sensor_list_and_real_prose():
    # ⛔ An empty set on either side makes every assertion below vacuous.
    assert _sensors_we_fetch(), "fixture problem: _FIRMS_SENSORS did not parse"
    prose = _locale_prose()
    assert len(prose) >= 2, f"fixture problem: {len(prose)} locale(s) discovered"
    assert all(len(v) > 200 for v in prose.values()), (
        f"fixture problem: fire prose per locale is too short to be real: "
        f"{ {k: len(v) for k, v in prose.items()} }"
    )


def test_no_locale_claims_a_sensor_family_we_never_request():
    fetched = _sensors_we_fetch()
    forbidden = KNOWN_SENSOR_WORDS - fetched
    offenders = {loc: sorted(w for w in forbidden if w in text)
                 for loc, text in _locale_prose().items()}
    offenders = {k: v for k, v in offenders.items() if v}
    assert not offenders, (
        f"we fetch {sorted(fetched)} and the copy promises {offenders}. "
        "A reader filtering by instrument is told about data never fetched."
    )


def test_no_backend_or_attribution_file_claims_one_either():
    fetched = _sensors_we_fetch()
    forbidden = KNOWN_SENSOR_WORDS - fetched
    offenders = {}
    for f in PROSE_FILES:
        assert f.is_file(), f"fixture problem: {f} is gone — the sweep is blind"
        text = f.read_text(encoding="utf-8")
        hits = [w for w in forbidden if re.search(rf"\b{w}\b", text)]
        if hits:
            offenders[f.name] = hits
    assert not offenders, (
        f"we fetch {sorted(fetched)}; these still claim {offenders}. The legal "
        "page and the export provenance are attributions, not marketing copy."
    )


def test_every_satellite_we_do_fetch_is_named_somewhere_a_reader_can_see():
    # The mirror of the test above. Omitting NOAA-21 while it supplies a third
    # of the rows is the same untruth pointed the other way.
    sats = _satellites_we_fetch()
    assert sats, "fixture problem: no satellites parsed out of _FIRMS_SENSORS"
    en = _locale_prose().get("en", "")
    missing = []
    for s in sats:
        # SNPP -> "Suomi-NPP" or "SNPP"; NOAA20 -> "NOAA-20" or "NOAA20"
        needle = s.replace("NOAA", "NOAA-?").replace("SNPP", "(Suomi-)?NPP")
        if not re.search(needle, en, re.IGNORECASE):
            missing.append(s)
    assert not missing, (
        f"these satellites are fetched but named nowhere in the English copy: "
        f"{missing}"
    )
