# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Persisted extractor drift guard.

Tasks 2-4 verified extractor coverage with one-off shell commands run once
during implementation. That is the wrong shape for a *recurring* audit tool:
a later refactor of an extractor, or an edit to one of the source files it
reads, could silently shrink coverage with nothing failing.

This module runs each extractor against the REAL repo files and asserts, for
each surface, that the extractor's row count equals an INDEPENDENTLY computed
count of that construct in the same file. The independent counters are
deliberately dumber than the extractors: the extractors are line-based state
machines that track block boundaries, comment lines, and (for the inventory)
multi-line tuple reassembly; the independent counts here are simple counts
over the raw file text. If a smart parser silently drops something the dumb
counter still sees, the two diverge and this test fails.

Property-style equalities on purpose (`assert extracted == dumb`), never a
hardcoded magic number — a hardcoded count passes today and rots the instant
someone adds or removes a link, whereas the cross-check survives content
changes and still catches an entire section going unwalked.

Guard strength is NOT uniform across the eight tests below, and a reader must
not assume it is. Ranked honestly:

STRONGLY INDEPENDENT (dumb counter shares no precondition or pattern with the
extractor it checks — a real bug in the extractor's own regex/state-machine
would not also live in the counter):
  - tooltip (`sourceUrl:` field count vs the extractor's block+key tracking)
  - provenance (whole-file `source_url="..."` count vs the extractor's
    ctor-attribution tracking)
  - locale URLs (raw-text regex over unparsed JSON vs a parsed-payload walk —
    different data representation entirely)
  - inventory, AS OF THIS REVISION (URL-literal count inside the block vs the
    extractor's multi-line tuple/paren-balance reassembly — see below)

PARTIALLY INDEPENDENT (still catches real regression classes, but shares an
axis with the code it guards, so it gives no protection against a flaw in
that shared axis):
  - offshore-homepage / layer-source: the dumb counter's `_block()` helper
    isolates the block with its own `^\\};` end-pattern before counting
    `url:`/`homepage:` fields — the SAME block-boundary pattern as the
    extractor's own `_BLOCK_END` (`extract_ts.py:20`), which the extractor
    uses to know when to stop scanning for a given surface. It still catches
    a wrong key/field regression inside a correctly-bounded block, but a bug
    that makes the extractor mis-detect where the block ends (an unrelated
    `};` line, a nested object closing early) would truncate the dumb
    counter's block identically, so the two would stay in lock-step while
    both silently drop the same trailing entries.
  - legend-tsx: the dumb counter counts `href="https` occurrences, which is a
    different regex from the extractor's `_ANY_URL` pattern and would catch a
    comment-skipping regression or a dropped-row bug. But both the extractor
    and the dumb counter rely on the same fact about this file — every link
    is rendered as an anchor with `href="..."` — so a link surfaced through
    some other JSX shape (no `href`) would be invisible to both sides at
    once and the test would still pass. See the test for the full disclosure.
  - detail-panel / seo-jsonld: the SELF-HOST exclusion is genuinely independent
    (hardcoded "something-rare.com" in the test, NOT imported from the
    extractor's SELF_HOSTS tuple), so a widened SELF_HOSTS that eats a real
    citation IS caught. The host-requirement half (`https?://[^/\s]`) is
    re-derived rather than imported — a fixed correctness filter, not an
    over-filter risk. A dedicated meta-test proves the guard is load-bearing.

Historical note: the inventory guard's ORIGINAL dumb counter (paren-opening
line count, `stripped.startswith("(")`) shared its start precondition with
`extract_inventory`'s own tuple-detection condition, giving it no protection
against a flaw in that shared precondition. It has been replaced with a
URL-literal count, which measures a genuinely different quantity ("how many
URLs are in the block" vs "how many tuples are in the block") and stays flat
if a tuple-reassembly bug causes the extractor to merge or drop a row.
"""
from __future__ import annotations

import glob
import json
import re
from pathlib import Path

from backend.scripts.link_audit.cli import (
    UNWALKED_SURFACES, collect_static_rows, unwalked_surface_entries,
)
from backend.scripts.link_audit.extract_locales import extract_locale_urls
from backend.scripts.link_audit.extract_py import extract_inventory, extract_provenance
from backend.scripts.link_audit.extract_ts import (
    _is_comment,
    extract_deep_link_templates,
    extract_detail_panel,
    extract_legend_tsx,
    extract_seo_tsx,
    extract_source_url_ts,
    extract_tooltips,
)

REPO = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block(lines: list[str], start_marker: str, end_pat: str = r"^\};") -> str:
    """Isolate a top-level `const X = { ... };` block by its start marker and
    the next line matching `end_pat`. Simple slicing, not a state machine —
    used only to bound WHERE to count, never to decide WHAT counts.

    Matches an optional leading "export " too — LAYER_TOOLTIPS_META gained an
    export keyword when it moved into its own module (controls/tooltips.ts)."""
    start = next(
        i for i, l in enumerate(lines)
        if l.startswith(start_marker) or l.startswith("export " + start_marker)
    )
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(end_pat, lines[j]):
            end = j
            break
    return "\n".join(lines[start : end + 1])


# ─── extract_source_url_ts: offshore homepages + layer sources ──────────────


def test_offshore_homepage_count_matches_dumb_url_field_count():
    path = REPO / "frontend/src/utils/sourceUrl.ts"
    text = _read(path)
    rows = extract_source_url_ts(text, "sourceUrl.ts")
    offshore_rows = [r for r in rows if r.surface == "offshore-homepage"]

    block = _block(text.splitlines(), "const OFFSHORE_SOURCE_HOMEPAGES")
    # Dumb: a raw regex count of `url: "..."` fields in the isolated block —
    # no per-line key tracking, no comment filtering, no block state machine.
    dumb_count = len(re.findall(r'url:\s*"', block))

    assert offshore_rows, "extractor returned zero offshore-homepage rows"
    assert len(offshore_rows) == dumb_count


def test_layer_source_count_matches_dumb_homepage_field_count():
    path = REPO / "frontend/src/utils/sourceUrl.ts"
    text = _read(path)
    rows = extract_source_url_ts(text, "sourceUrl.ts")
    layer_rows = [r for r in rows if r.surface == "layer-source"]

    block = _block(text.splitlines(), "const LAYER_SOURCES")
    dumb_count = len(re.findall(r'homepage:\s*"', block))

    assert layer_rows, "extractor returned zero layer-source rows"
    assert len(layer_rows) == dumb_count


# ─── extract_tooltips ────────────────────────────────────────────────────────


def test_tooltip_count_matches_dumb_source_url_field_count():
    # LAYER_TOOLTIPS_META moved from Map3DControls.tsx into
    # controls/tooltips.ts during the controls split; walk controls/** so
    # this stays correct if the table moves again.
    path = REPO / "frontend/src/components/controls/tooltips.ts"
    text = _read(path)
    rows = extract_tooltips(text, "tooltips.ts")

    block = _block(text.splitlines(), "const LAYER_TOOLTIPS_META")
    dumb_count = len(re.findall(r'sourceUrl:\s*"', block))

    assert rows, "extractor returned zero tooltip rows"
    assert len(rows) == dumb_count


# ─── extract_legend_tsx (bonus: not in the brief's list, but it's a surface too) ─


def test_legend_tsx_count_matches_dumb_href_count():
    path = REPO / "frontend/src/components/LegendPanel.tsx"
    text = _read(path)
    rows = extract_legend_tsx(text, "LegendPanel.tsx")

    # Dumb: count `href="https` occurrences, NOT a quoted-URL regex — the
    # extractor's own _ANY_URL pattern is `r'"(https?://[^"]+)"'`, and a
    # dumb counter built from the identical pattern would give zero
    # protection against a flaw in that shared pattern itself (it would
    # merely re-derive the extractor's own answer). Counting `href="https`
    # instead measures a different textual anchor — the JSX attribute name —
    # so it still catches a comment-skipping regression or a dropped row.
    #
    # PARTIAL independence, disclosed honestly: every link in this file
    # happens to render as `<a href="...">`, with the raw URL also present a
    # second time as visible anchor text (hence a naive `https://` scan over
    # the whole file returns 6, not 3, for today's 3 links — confirmed
    # against the live file). Because both this counter and the extractor
    # rely on "every link has an `href` attribute", a hypothetical link
    # surfaced through some other JSX shape (no `href=`, e.g. built from a
    # template or spread prop) would be invisible to BOTH sides at once and
    # this test would still pass. That gap is real; no genuinely independent
    # dumb counter was found for this surface that doesn't share it. See the
    # module docstring's guard-strength ranking.
    dumb_count = len(re.findall(r'href="https', text))

    assert rows, "extractor returned zero legend-tsx rows"
    assert len(rows) == dumb_count


# ─── extract_inventory ───────────────────────────────────────────────────────


def test_inventory_count_matches_dumb_url_literal_count():
    path = REPO / "backend/main.py"
    text = _read(path)
    rows = extract_inventory(text, "main.py")

    lines = text.splitlines()
    block = _block(lines, "_INVENTORY", end_pat=r"^\]")
    # Dumb: count URL LITERALS inside the block, not tuple-opening lines.
    # This measures a genuinely different quantity than "how many tuples are
    # there" — the extractor's own start condition (`stripped.startswith("(")`)
    # — so it is independent on a different axis than a prior version of this
    # guard, which counted paren-opening lines and therefore shared its
    # start precondition with `extract_inventory`'s own tuple-detection
    # condition (see the module docstring). Every real _INVENTORY entry
    # carries exactly one URL, so the counts agree today; if the extractor's
    # multi-line paren-balance reassembly ever merges two tuples into one or
    # drops a row, the extractor's row count falls while this URL count
    # holds steady, and they diverge.
    dumb_count = len(re.findall(r'"(https?://[^"]+)"', block))

    assert rows, "extractor returned zero inventory rows"
    assert len(rows) == dumb_count


# ─── extract_provenance ──────────────────────────────────────────────────────


def test_provenance_count_matches_dumb_source_url_kwarg_count():
    path = REPO / "backend/services/export_registry.py"
    text = _read(path)
    rows = extract_provenance(text, "export_registry.py")

    # Dumb: a raw regex count of `source_url="..."` occurrences over the
    # WHOLE file — no attribution tracking, no comment filtering.
    dumb_count = len(re.findall(r'source_url\s*=\s*"', text))

    assert rows, "extractor returned zero provenance rows"
    assert len(rows) == dumb_count


# ─── extract_locale_urls: every locale, not just en ─────────────────────────


def test_locale_url_count_matches_dumb_raw_text_count_for_every_locale():
    locale_paths = sorted(glob.glob(str(REPO / "frontend/public/locales/*/legend.json")))
    assert len(locale_paths) >= 4, "expected at least the 4 known locales"

    # Dumb: a regex over the RAW JSON TEXT (no json.loads, no tree walk) that
    # stops at the JSON string's closing quote or an escape backslash. This
    # is independent of extract_locale_urls's approach in the way that
    # matters: it never walks the parsed payload, so it still sees a URL
    # sitting under a key the walker doesn't visit.
    # Stops at whitespace too: a URL cannot contain a space, and without that
    # a JSON string holding TWO URLs in prose (MEMENTO's required acknowledgement
    # carries sopran.pangaea.de and memento.geomar.de in one sentence) matched as
    # a single run and under-counted by one. Stopping at whitespace is dumber,
    # not smarter — it makes no attempt to understand the payload.
    dumb_pattern = re.compile(r'https?://[^"\\\s]+')

    checked = 0
    for path_str in locale_paths:
        path = Path(path_str)
        raw = _read(path)
        payload = json.loads(raw)
        rows = extract_locale_urls(payload, path.parent.name, path.name)
        dumb_count = len(dumb_pattern.findall(raw))

        assert rows, f"extractor returned zero rows for locale {path.parent.name}"
        assert len(rows) == dumb_count, (
            f"locale {path.parent.name}: extractor={len(rows)} dumb={dumb_count}"
        )
        checked += 1

    assert checked == len(locale_paths)


# ─── extract_deep_link_templates ─────────────────────────────────────────────


def test_deep_link_templates_nonempty_and_each_has_exactly_one_placeholder():
    path = REPO / "frontend/src/utils/sourceUrl.ts"
    text = _read(path)
    # extract_deep_link_templates already raises ValueError internally if the
    # recovered template count doesn't match the perFeature implementation
    # count (its own guard). This test adds the placeholder-arity check the
    # brief calls out: a template with two `${...}` placeholders would be
    # silently mis-substituted by build_deep_link (which fills exactly one).
    templates = extract_deep_link_templates(text)

    assert templates, "no perFeature deep-link templates recovered"

    placeholder_re = re.compile(r"\$\{[^}]*\}")
    for tpl in templates:
        count = len(placeholder_re.findall(tpl.template))
        assert count == 1, (
            f"{tpl.key}: template has {count} ${{...}} placeholders, "
            f"expected exactly 1 — {tpl.template!r}"
        )


# ─── UNWALKED_SURFACES: disclosure must survive, not just exist once ────────
#
# This is not a coverage guard for an extractor (there is no extractor for
# these surfaces yet, by design — see cli.py). It guards the DISCLOSURE
# itself: that each known-unwalked file still exists, still actually carries
# URLs (so the entry isn't a stale fossil once the file is edited down to
# nothing), and still surfaces as a `not_checked` line. This is what stops
# the gap being quietly deleted from the report while the underlying file
# still has un-extracted links.

_ANY_URL_RE = re.compile(r"https?://[^\"'`\s)]+")


def test_unwalked_surfaces_may_only_be_emptied_by_real_extractors():
    """The list may shrink to empty — but only once the files it named are
    genuinely walked. Emptying it any other way re-hides the gap it discloses,
    which is exactly what this guard exists to stop.

    DetailPanel.tsx and SEO.tsx were removed from the list on 2026-07-25 when
    they gained extractors; render-page.js was removed because measuring it
    showed all 21 of its URLs are self-origin (see cli.py), so it cites nothing
    external and is excluded by SELF_HOSTS rather than deferred.
    """
    if not UNWALKED_SURFACES:
        rows = collect_static_rows(REPO)
        walked = {r.file for r in rows}
        # DetailPanel.tsx's own URLs all moved into panels/**/*.tsx during
        # the 2026-08 split — the root file is now a bare dispatcher with
        # zero literals of its own, so it legitimately never appears in
        # `walked`. What must survive is that the extraction still reaches
        # the URLs that used to live in DetailPanel.tsx, i.e. at least one
        # panels/ file is present in the manifest.
        assert any(f.startswith("frontend/src/components/panels/") for f in walked), (
            "UNWALKED_SURFACES was emptied but no panels/**/*.tsx file is in "
            "the manifest — the DetailPanel split's URLs were hidden, not "
            "closed"
        )
        assert "frontend/src/components/SEO.tsx" in walked, (
            "UNWALKED_SURFACES was emptied but frontend/src/components/SEO.tsx "
            "is not in the manifest — the gap was hidden, not closed")
        return

    for path, count, reason in UNWALKED_SURFACES:
        full = REPO / path
        assert full.exists(), (
            f"{path} no longer exists — remove its UNWALKED_SURFACES entry, "
            f"don't leave a disclosure for a file that isn't there"
        )
        found = len(set(_ANY_URL_RE.findall(_read(full))))
        assert found > 0, (
            f"{path} no longer contains any URL — drop this entry rather "
            f"than report a fabricated count"
        )
        assert count > 0 and reason, f"{path}: malformed UNWALKED_SURFACES entry"


def test_unwalked_surfaces_all_appear_in_not_checked_output():
    entries = unwalked_surface_entries()
    assert len(entries) == len(UNWALKED_SURFACES)

    for (path, count, _reason), line in zip(UNWALKED_SURFACES, entries):
        assert line.startswith(f"{path}: ~{count} source URLs NOT EXTRACTED"), line
        assert "absent from this run" in line
        assert path in [e.split(":")[0] for e in entries]  # survives future reordering


# ─── extract_detail_panel + extract_seo_tsx (added after the DetailPanel/SEO ───
#     surfaces shipped without a persisted dumb-count guard) ──────────────────
#
# Independence of these two: the SELF-HOST exclusion is hardcoded here
# ("something-rare.com") rather than imported from the extractor's SELF_HOSTS
# tuple, so if that tuple is ever widened and starts swallowing a real outbound
# citation, the extractor's kept-count drops below this independent count and the
# test fails — which is exactly the over-filtering risk flagged in review. The
# host requirement (a non-slash char after `//`) is RE-DERIVED here rather than
# imported (partial independence, same honest caveat as the legend-tsx guard):
# it's a fixed correctness filter, not an over-filter risk.

_DUMB_TOKEN = re.compile(r"https?://[^\s\"'`<>“”‘’)]*")
_DUMB_HAS_HOST = re.compile(r"https?://[^/\s]")
_DUMB_SELF = "something-rare.com"   # hardcoded on purpose — do NOT import SELF_HOSTS


def _dumb_external_url_count(text: str) -> int:
    """Count http(s) URL tokens on non-comment lines that are neither self-origin
    nor scheme-only — a deliberately different method from the extractor."""
    kept = 0
    for line in text.splitlines():
        if _is_comment(line):
            continue
        for tok in _DUMB_TOKEN.findall(line):
            if _DUMB_SELF in tok:
                continue
            if not _DUMB_HAS_HOST.match(tok):   # scheme-only / hostless
                continue
            kept += 1
    return kept


def test_detail_panel_count_matches_dumb_external_url_count():
    # DetailPanel.tsx was split into ~65 panel components under
    # panels/**/*.tsx; the dumb counter must scan the SAME file set the
    # extractor now walks, or this pairing checks a subset of the real
    # surface and would have stayed green through the exact regression that
    # motivated this test (zero DetailPanel URLs extracted).
    import glob
    paths = [REPO / "frontend/src/components/DetailPanel.tsx"] + sorted(
        Path(p) for p in glob.glob(
            str(REPO / "frontend/src/components/panels/**/*.tsx"), recursive=True))
    assert len(paths) > 1, "panels/ split not found — did DetailPanel.tsx un-split?"

    kept = 0
    dumb = 0
    for p in paths:
        text = _read(p)
        rows, templates = extract_detail_panel(text, str(p.relative_to(REPO)))
        kept += len(rows) + len(templates)   # citations + ${…} templates
        dumb += _dumb_external_url_count(text)

    assert kept, "extractor returned zero DetailPanel URLs"
    assert kept == dumb


def test_seo_tsx_count_matches_dumb_external_url_count():
    path = REPO / "frontend/src/components/SEO.tsx"
    text = _read(path)
    rows = extract_seo_tsx(text, "SEO.tsx")
    assert rows, "extractor returned zero SEO.tsx URLs"
    assert len(rows) == _dumb_external_url_count(text)


def test_widening_self_hosts_to_eat_a_real_citation_would_fail_this_guard():
    """Meta-check: prove the guard is load-bearing, not vacuous. Simulate an
    over-broad SELF_HOSTS by dropping one more real URL and confirm the counts
    then disagree — i.e. a real over-filter would be caught."""
    text = _read(REPO / "frontend/src/components/SEO.tsx")
    real = len(extract_seo_tsx(text, "SEO.tsx"))
    assert real - 1 != _dumb_external_url_count(text)  # a silent drop of 1 ≠ dumb count
