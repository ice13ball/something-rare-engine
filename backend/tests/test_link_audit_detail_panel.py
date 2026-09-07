# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""DetailPanel.tsx / SEO.tsx extraction.

Every snippet here is copied VERBATIM from the real files (as they stood
2026-07-25) rather
than invented, so a green test means the extractor handles the shapes that
actually ship. Line 2978's nested backtick and line 3216's bare scheme are the
two constructs that broke naive approaches during development; both are locked
below.
"""
from __future__ import annotations

import pytest

from backend.scripts.link_audit.extract_ts import (
    extract_detail_panel, extract_seo_tsx,
)
from backend.scripts.link_audit.sample import (
    DETAIL_TEMPLATE_LAYERS, build_detail_link, prefix_row,
)
from backend.scripts.link_audit.models import DetailTemplate, LinkRow
from backend.scripts.link_audit.cli import downgrade_prefix_only_dead, prefix_only_urls


# ── extraction ───────────────────────────────────────────────────────────────

def test_splits_literals_from_templates():
    src = '\n'.join([
        '        href="https://doi.org/10.1594/PANGAEA.917894"',
        '            href={`https://obis.org/occurrence/${p.obis_id}`}',
    ])
    rows, tpls = extract_detail_panel(src, "DetailPanel.tsx")

    assert [r.url_raw for r in rows] == ["https://doi.org/10.1594/PANGAEA.917894"]
    assert rows[0].surface == "detail-citation"
    assert rows[0].kind == "doi"
    assert [t.template for t in tpls] == ["https://obis.org/occurrence/${p.obis_id}"]
    assert tpls[0].prefix == "https://obis.org/occurrence/"


def test_backtick_literal_without_placeholder_is_a_citation():
    """`https://www.mbari.org/data/` is a plain URL that merely uses backticks."""
    rows, tpls = extract_detail_panel(
        '    return `https://www.mbari.org/data/`;', "DetailPanel.tsx")
    assert [r.url_raw for r in rows] == ["https://www.mbari.org/data/"]
    assert tpls == []


def test_nested_backtick_yields_the_true_static_prefix():
    """DetailPanel.tsx:2978 — a template literal nested inside ${...}.

    The inner backtick closes the outer literal, which is what makes the
    recovered prefix correct. A URL-first regex instead runs on into the nested
    expression and yields a prefix that was never a URL.
    """
    src = ('{country != null && <ExternalLink href={`https://www.google.com/'
           'search?q=${encodeURIComponent(`${ftype} mining ${country}`)}`} />}')
    rows, tpls = extract_detail_panel(src, "DetailPanel.tsx")
    assert rows == []
    assert len(tpls) == 1
    assert tpls[0].prefix == "https://www.google.com/search?q="


def test_bare_scheme_is_not_a_citation():
    """DetailPanel.tsx:3216 tests the scheme; it is not a link to anything."""
    src = ('  const isUrl = sourceUrl && (sourceUrl.startsWith("http://") '
           '|| sourceUrl.startsWith("https://"));')
    rows, tpls = extract_detail_panel(src, "DetailPanel.tsx")
    assert (rows, tpls) == ([], [])


def test_self_origin_is_excluded():
    """server.js's catch-all makes every something-rare.com path return 200."""
    src = '  <a href="https://something-rare.com/report/x">r</a>'
    assert extract_detail_panel(src, "f")[0] == []
    assert extract_seo_tsx(src, "f") == []


def test_comment_lines_are_ignored():
    src = '  // dead upstream: https://vents-data.interridge.org'
    assert extract_detail_panel(src, "f") == ([], [])


def test_guard_fires_when_a_url_escapes_every_string_literal():
    """A URL in a JSX text node is rendered but recovered by no literal scan."""
    with pytest.raises(ValueError, match="string-literal guard"):
        extract_detail_panel("  <p>see https://example.org/docs</p>", "f")


def test_seo_rows_carry_the_jsonld_surface():
    src = '  identifier: "https://doi.org/10.5281/zenodo.19745884",'
    rows = extract_seo_tsx(src, "SEO.tsx")
    assert [(r.surface, r.kind) for r in rows] == [("seo-jsonld", "doi")]


# ── plane B: substitution ────────────────────────────────────────────────────

def _tpl(template: str) -> DetailTemplate:
    return DetailTemplate(template=template, prefix=template.split("${", 1)[0],
                          file="DetailPanel.tsx", line=1)


def test_build_detail_link_substitutes_a_real_property():
    # Was the Protected Planet template until 2026-09-03; WDPA was withdrawn and
    # its mapping deleted, so this exercises a surviving one. The assertion is
    # about substitution, not about which layer happens to supply the example.
    t = _tpl("https://explore.openaq.org/locations/${locationId}")
    assert build_detail_link(t, {"location_id": 555629}) == \
        "https://explore.openaq.org/locations/555629"


def test_repeated_placeholder_is_filled_everywhere():
    """`…/${slug}/${slug}.zip` reads one variable twice."""
    t = _tpl("https://datasets.obis.org/hosted/isa/${slug}/${slug}.zip")
    assert build_detail_link(t, {"archive_slug": "nori-d"}) == \
        "https://datasets.obis.org/hosted/isa/nori-d/nori-d.zip"


def test_unmapped_template_builds_nothing():
    """A bbox builder has no single substitutable property — never invent one."""
    t = _tpl("https://mapper.obis.org/?bbox=${lonMin},${latMin}")
    assert build_detail_link(t, {"lon": 1, "lat": 2}) is None


def test_absent_property_builds_nothing():
    t = _tpl("https://www.protectedplanet.net/${wdpaId}")
    assert build_detail_link(t, {"name": "Ha Long Bay"}) is None


def test_prefix_row_is_marked_as_the_weaker_check():
    row = prefix_row(_tpl("https://explore.openaq.org/locations/${locId}"))
    assert row.surface == "detail-prefix"
    assert row.url_normalized == "https://explore.openaq.org/locations/"


def test_every_mapped_prefix_is_a_prefix_of_a_real_template(repo_detail_templates):
    """The map must not drift from the file it describes.

    A prefix that matches no live template is a dead entry that would quietly
    stop contributing coverage — the same silent-shrink failure the count
    guards exist to prevent. The templates DETAIL_TEMPLATE_LAYERS maps now
    live across DetailPanel.tsx's per-family panel components under
    panels/**/*.tsx (post-split), not the root file alone.
    """
    live = {t.prefix for t in repo_detail_templates}
    assert set(DETAIL_TEMPLATE_LAYERS) <= live, (
        f"stale DETAIL_TEMPLATE_LAYERS entries: "
        f"{set(DETAIL_TEMPLATE_LAYERS) - live}")


@pytest.fixture
def repo_detail_templates() -> list[DetailTemplate]:
    from backend.scripts.link_audit.cli import collect_detail_templates
    from pathlib import Path
    repo = Path(__file__).resolve().parents[2]
    p = repo / "frontend/src/components/DetailPanel.tsx"
    if not p.exists():
        pytest.skip("DetailPanel.tsx not present")
    return collect_detail_templates(repo)


# ── prefix-only DEAD is an artefact, not a finding ───────────────────────────

def test_prefix_only_dead_is_downgraded():
    """`https://doi.pangaea.de/10.1594/` 404s because it is a DOI stem.

    Real run, 2026-07-25: this and explore.openaq.org/locations/ were the only
    two DEADs that came from prefixes rather than from links the product renders.
    """
    only = {"https://doi.pangaea.de/10.1594/"}
    assert downgrade_prefix_only_dead(
        "DEAD", "https://doi.pangaea.de/10.1594/", only) == "NOT_CHECKED"


def test_live_prefix_keeps_its_verdict():
    only = {"https://obis.org/occurrence/"}
    assert downgrade_prefix_only_dead(
        "OK", "https://obis.org/occurrence/", only) == "OK"


def test_dead_on_a_rendered_link_is_never_downgraded():
    """obis.org/area?nodeid=… is a real DetailPanel citation — it must stay DEAD."""
    url = "https://obis.org/area?nodeid=9d2d95be-32eb-4d81-8911-32cb8bc641c8"
    assert downgrade_prefix_only_dead("DEAD", url, set()) == "DEAD"


def test_prefix_only_excludes_urls_that_also_render_for_real():
    """A URL used BOTH as a prefix and as a real citation is not prefix-only."""
    rows = [
        LinkRow(layer_id="x", surface="detail-prefix", url_raw="https://a/",
                url_normalized="https://a/", kind="homepage", file="f", line=1),
        LinkRow(layer_id="x", surface="detail-citation", url_raw="https://a/",
                url_normalized="https://a/", kind="homepage", file="f", line=2),
        LinkRow(layer_id="x", surface="detail-prefix", url_raw="https://b/",
                url_normalized="https://b/", kind="homepage", file="f", line=3),
    ]
    assert prefix_only_urls(rows) == {"https://b/"}
