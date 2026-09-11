# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The dams layer described a dataset we never loaded.

The legend promised Global Dam Watch GDW v1.1 — "41,145 river barriers ... Each
record includes dam name, river, country, height (metres), purpose, year
completed, reservoir storage volume, and dam type" — and the tooltip added
"35,295 reservoir polygons".

What is actually loaded, read off the source file on the VPS 2026-09-10:

    /opt/abyssal-data/dams/Data/GOOD2_dams.shp   (GOODD v2, dated 2019-08-16)
    Feature Count: 38667
    Fields: DAM_ID, Count_ID, Latitud, Longitud

GOODD georeferences dams. It publishes no name, river, country, height,
purpose, year or volume, and no reservoir polygons at all. Confirmed against
production the same day:

    38,667 rows
    dam_name  38,667 populated — every value a bare sequential integer from
              1000000, which is GOODD's DAM_ID
    river, country, height_m, purpose, year_built, volume_mcm — 0 populated
    no reservoir/catchment table exists anywhere in the database

⛔ An internal identifier rendered as a dam's name is worse than an empty
field: it looks like data, and the panel's Wikipedia link searched for
"1000000 dam", a query that cannot succeed.

⛔ NOT fixed here, because it cannot be: the loader is append-only and guarded
against re-running, so correcting the DATA needs a deliberate TRUNCATE. That is
Michal's call, and sourcing the real GDW release — which does carry the
attributes — is the better answer than reloading GOODD.
"""
import json
import pathlib
import re

ROOT    = pathlib.Path(__file__).resolve().parents[2]
LOCALES = ROOT / "frontend" / "public" / "locales"
PANEL   = ROOT / "frontend" / "src" / "components" / "panels" / "land" / "DamPanel.tsx"
TYPES   = ROOT / "frontend" / "src" / "types" / "landLayers.ts"

#: Columns the legend used to promise that GOODD does not carry. Measured 0%
#: populated on production; the copy must not claim them until they are.
UNPOPULATED = ("river", "country", "height_m", "purpose", "year_built", "volume_mcm")

#: Counts quoted from the GDW release we never loaded.
_WRONG_COUNTS = re.compile(r"41[,. ]?145|35[,. ]?295")


def _locales():
    return sorted(p for p in LOCALES.iterdir() if (p / "legend.json").is_file())


def test_the_fixture_finds_the_layer_in_every_locale():
    for loc in _locales():
        d = json.loads((loc / "legend.json").read_text(encoding="utf-8"))
        assert "globalDams" in d["layers"], f"fixture problem: {loc.name} has no globalDams"
    assert len(_locales()) >= 2


def test_no_locale_quotes_a_record_count_from_a_dataset_we_did_not_load():
    offenders = {}
    for loc in _locales():
        blob = (loc / "legend.json").read_text(encoding="utf-8")
        if (loc / "panels.json").is_file():
            blob += (loc / "panels.json").read_text(encoding="utf-8")
        hit = _WRONG_COUNTS.findall(blob)
        if hit:
            offenders[loc.name] = hit
    assert not offenders, (
        f"these locales still quote GDW's counts {offenders}; the loaded GOODD "
        "file holds 38,667 dams and no reservoir polygons at all"
    )
    assert not _WRONG_COUNTS.search(TYPES.read_text(encoding="utf-8")), (
        "landLayers.ts still quotes the GDW counts"
    )


def test_the_layer_says_it_carries_locations_only():
    # ⛔ Positive assertion, not just an absence. Deleting the false promise and
    # saying nothing would leave six empty rows reading as a failed fetch.
    for loc in _locales():
        d = json.loads((loc / "legend.json").read_text(encoding="utf-8"))
        blob = "\n".join(str(v) for v in d["layers"]["globalDams"].values())
        assert "GOODD" in blob, f"{loc.name} does not name the dataset actually loaded"
        assert re.search(r"only|tylko|seul|nur", blob, re.IGNORECASE), (
            f"{loc.name} does not tell the reader this source carries locations only"
        )


def test_no_locale_promises_an_attribute_goodd_does_not_publish():
    # The English wording is the one that listed them; check every locale for a
    # sentence claiming each record INCLUDES those fields.
    claims = re.compile(
        r"(each record includes|record includes|includes dam name)"
        r"|(każdy rekord zawiera)"
        r"|(chaque enregistrement (comprend|inclut))"
        r"|(jeder datensatz enthält)", re.IGNORECASE)
    # ⛔ Scoped to the globalDams entry. A whole-file search reddened on the
    # landslides and chess entries, which legitimately say "Each record
    # includes ..." about fields those sources really do publish.
    offenders = []
    for loc in _locales():
        d = json.loads((loc / "legend.json").read_text(encoding="utf-8"))
        blob = "\n".join(str(v) for v in d["layers"]["globalDams"].values())
        if claims.search(blob):
            offenders.append(loc.name)
    assert not offenders, (
        f"{offenders} still claim each record carries attributes; on production "
        f"{list(UNPOPULATED)} are 0% populated across all 38,667 rows"
    )


def test_the_panel_does_not_render_an_internal_id_as_a_name():
    panel = PANEL.read_text(encoding="utf-8")
    assert "isBareId" in panel, (
        "DamPanel shows dam_name straight as the header again; on production "
        "every value is a bare integer from GOODD's DAM_ID"
    )
    # And the dead Wikipedia search must stay gated on a real name.
    m = re.search(r"\{name && <ExternalLink href=\{`https://en\.wikipedia\.org", panel)
    assert m, (
        'the Wikipedia link is no longer gated on a real name — it would search '
        'for "1000000 dam", which cannot succeed'
    )
