# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import json
import os
import re
from pathlib import Path

from backend.scripts.link_audit.extract_locales import (
    extract_locale_urls, find_locale_divergence,
)
from backend.scripts.link_audit.models import UNATTRIBUTED

_REAL_EN_LEGEND = os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend", "public", "locales", "en", "legend.json",
)

_REAL_EN_LEGEND_PATH = Path(__file__).parent.parent.parent / "frontend" / "public" / "locales" / "en" / "legend.json"

# Same stop-set as the extractor's _URL_IN_PROSE: whitespace, quotes, angle
# brackets (i18n <1> markers), parens, backslash.
_URL_ANYWHERE = re.compile(r"https?://[^\s\"'<>)\\]+")


def _count_urls_anywhere(node) -> int:
    """Independently walk the raw JSON and count every URL occurrence,
    regardless of which top-level section it lives under."""
    if isinstance(node, str):
        return len(_URL_ANYWHERE.findall(node))
    if isinstance(node, dict):
        return sum(_count_urls_anywhere(v) for v in node.values())
    if isinstance(node, list):
        return sum(_count_urls_anywhere(v) for v in node)
    return 0


def test_extracts_url_embedded_in_i18n_prose_without_trailing_markup():
    """legend.json embeds URLs inside <Trans> prose, so a naive [^"]* regex
    swallows the closing tag: `…PANGAEA.917894</1>. Each vent entry…`."""
    payload = {"layers": {"hydrothermal-vents": {
        "description": "See <1>https://doi.org/10.1594/PANGAEA.917894</1>. Each vent entry includes the reference.",
    }}}
    rows = extract_locale_urls(payload, "en", "locales/en/legend.json")
    assert len(rows) == 1
    assert rows[0].url_normalized == "https://doi.org/10.1594/PANGAEA.917894"
    assert rows[0].layer_id == "hydrothermal-vents"
    assert rows[0].surface == "legend-locale"


def test_extracts_datasources_array_urls():
    payload = {"layers": {"cables": {
        "dataSources": [{"name": "EMODnet", "url": "https://emodnet.ec.europa.eu/"}],
    }}}
    rows = extract_locale_urls(payload, "en", "locales/en/legend.json")
    assert [r.url_normalized for r in rows] == ["https://emodnet.ec.europa.eu/"]


def test_divergence_flags_a_locale_that_missed_a_url_fix():
    """The defect class no HTTP check can see: en was fixed, pl still cites the
    retired URL. Both return 200; only one is correct."""
    en = extract_locale_urls(
        {"layers": {"x": {"description": "https://new.example.org/"}}}, "en", "en/legend.json")
    pl = extract_locale_urls(
        {"layers": {"x": {"description": "https://old.example.org/"}}}, "pl", "pl/legend.json")
    div = find_locale_divergence({"en": en, "pl": pl})
    assert len(div) == 1
    assert div[0]["locale"] == "pl"
    assert div[0]["missing"] == ["https://new.example.org/"]
    assert div[0]["extra"] == ["https://old.example.org/"]


def test_no_divergence_when_locales_agree():
    rows = lambda loc: extract_locale_urls(
        {"layers": {"x": {"description": "https://same.example.org/"}}}, loc, f"{loc}/legend.json")
    assert find_locale_divergence({"en": rows("en"), "pl": rows("pl")}) == []


def test_extracts_clean_url_from_real_en_legend_json():
    """Ground-truth check against the real file, not a synthetic payload.

    The `hydrothermalVents.source` field of the real
    frontend/public/locales/en/legend.json contains, verbatim:
      "...PANGAEA, https://doi.org/10.1594/PANGAEA.917894"
    (verified by reading the file directly). This asserts the extractor pulls
    that exact URL out cleanly from the real document, with no leftover
    markup or trailing prose.
    """
    with open(_REAL_EN_LEGEND, encoding="utf-8") as f:
        payload = json.load(f)

    rows = extract_locale_urls(payload, "en", _REAL_EN_LEGEND)
    assert len(rows) > 0

    target = "https://doi.org/10.1594/PANGAEA.917894"
    matches = [r for r in rows if r.url_normalized == target]
    assert matches, f"expected {target!r} to be extracted from the real en/legend.json"
    for r in matches:
        assert "<" not in r.url_normalized
        assert ">" not in r.url_normalized
        assert r.url_normalized == target  # no trailing prose/markup appended


def test_extractor_covers_every_url_in_the_real_file_not_just_layers():
    """Regression for the coverage defect: extract_locale_urls used to walk
    only payload["layers"], silently missing URLs under `verify` (and any
    other top-level section like `dates`/`inventory`/`footer`).

    Asserted as a property, not a magic number: the count the extractor
    returns must equal an independently-computed count of every URL anywhere
    in the raw JSON. Also asserts at least one row is bucketed UNATTRIBUTED
    (a non-`layers` URL) and that no returned url_normalized carries stray
    `<`/`>` i18n markup.
    """
    with _REAL_EN_LEGEND_PATH.open(encoding="utf-8") as f:
        payload = json.load(f)

    expected_total = _count_urls_anywhere(payload)
    rows = extract_locale_urls(payload, "en", str(_REAL_EN_LEGEND_PATH))

    assert len(rows) == expected_total

    unattributed = [r for r in rows if r.layer_id == UNATTRIBUTED]
    assert unattributed, "expected at least one URL outside `layers` (e.g. under `verify`)"

    for r in rows:
        assert "<" not in r.url_normalized
        assert ">" not in r.url_normalized
