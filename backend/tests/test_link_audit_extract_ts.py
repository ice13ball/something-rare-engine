# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from pathlib import Path

import pytest

from backend.scripts.link_audit.extract_ts import (
    extract_deep_link_templates,
    extract_source_url_ts,
    extract_tooltips,
)

FIXTURES = Path(__file__).parent / "fixtures" / "link_audit"


def _rows():
    text = (FIXTURES / "sourceUrl_excerpt.ts").read_text(encoding="utf-8")
    return extract_source_url_ts(text, "frontend/src/utils/sourceUrl.ts")


def test_extracts_offshore_homepages_with_registry_key():
    rows = [r for r in _rows() if r.surface == "offshore-homepage"]
    assert {r.layer_id for r in rows} == {"emodnet", "boem", "crown_estate"}
    emodnet = next(r for r in rows if r.layer_id == "emodnet")
    assert emodnet.url_normalized == "https://emodnet.ec.europa.eu/en/human-activities"
    assert emodnet.kind == "homepage"


def test_extracts_layer_source_homepages_with_quoted_key():
    rows = [r for r in _rows() if r.surface == "layer-source"]
    assert {r.layer_id for r in rows} == {"isa-contract", "interridge-vent"}


def test_doi_homepage_is_classified_as_doi():
    rows = _rows()
    vent = next(r for r in rows if r.layer_id == "interridge-vent")
    assert vent.kind == "doi"
    assert vent.url_normalized == "https://doi.org/10.1594/PANGAEA.917894"


def test_commented_out_url_is_not_extracted():
    """The interridge-vent entry has a comment naming vents-data.interridge.org.
    A naive 'find every URL-ish token' extractor would emit it as a live link."""
    rows = _rows()
    assert not any("interridge.org" in r.url_raw and "doi.org" not in r.url_raw
                   for r in rows)


def test_line_numbers_are_one_based_and_point_at_the_url():
    rows = _rows()
    emodnet = next(r for r in rows if r.layer_id == "emodnet")
    text = (FIXTURES / "sourceUrl_excerpt.ts").read_text(encoding="utf-8")
    assert text.splitlines()[emodnet.line - 1].strip().startswith("emodnet:")


def _templates():
    text = (FIXTURES / "sourceUrl_excerpt.ts").read_text(encoding="utf-8")
    return {t.key: t for t in extract_deep_link_templates(text)}


def test_recovers_template_literal_and_props():
    obis = _templates()["obis-occurrence"]
    assert obis.template == "https://obis.org/occurrence/${id}"
    assert "obis_id" in obis.props


def test_recovers_template_wrapped_in_encodeuricomponent():
    argo = _templates()["argo-float"]
    assert argo.template.startswith("https://fleetmonitoring.euro-argo.eu/float/")
    assert "platform_id" in argo.props


def test_obis_props_are_not_contaminated_by_the_next_entrys_builder():
    """Regression for a fixed 20-line body window: obis-occurrence sits
    directly above argo-float in the fixture, and argo-float's builder
    (p.platform_id / p.platformId / p.wmo) falls inside that window. A body
    that isn't bounded to obis-occurrence's own perFeature block leaks those
    names into its props. Exact equality (not membership) is required to
    catch the leak."""
    obis = _templates()["obis-occurrence"]
    assert obis.props == ("obis_id", "id")


def test_only_perfeature_implementations_counted_not_the_interface_declaration():
    """`perFeature?: (p: Properties) => string | null;` is a type declaration,
    not a builder. Counting it would trip the guard on every run."""
    text = 'interface SourceEntry {\n  perFeature?: (p: Properties) => string | null;\n}\n'
    assert extract_deep_link_templates(text) == []


def test_guard_raises_when_a_builder_is_missed():
    """A perFeature whose URL is not a template literal must fail loudly rather
    than silently reduce audit coverage."""
    text = (
        'const X: Record<string, SourceEntry> = {\n'
        '  "weird": {\n'
        '    homepage: "https://example.org/",\n'
        '    perFeature: (p) => buildSomewhereElse(p),\n'
        '  },\n'
        '};\n'
    )
    with pytest.raises(ValueError, match="perFeature"):
        extract_deep_link_templates(text)


def test_tooltips_attribute_url_to_the_layer_key():
    text = (FIXTURES / "tooltips_excerpt.tsx").read_text(encoding="utf-8")
    rows = {r.layer_id: r for r in extract_tooltips(text, "frontend/src/components/Map3DControls.tsx")}
    assert set(rows) == {"contracts", "ocean-currents", "woa-climatology"}
    assert rows["ocean-currents"].url_normalized.startswith("https://data.marine.copernicus.eu/")
    assert rows["contracts"].surface == "tooltip"
