# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Assemble the manifest, fetch every unique URL once, write results.

Usage:
    python3 -m backend.scripts.link_audit.cli --repo . --out /tmp/link-audit
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
from dataclasses import asdict
from pathlib import Path

from .extract_locales import extract_locale_urls, find_locale_divergence
from .extract_py import extract_inventory, extract_provenance
from .extract_ts import (
    extract_deep_link_templates, extract_detail_panel, extract_legend_tsx,
    extract_seo_tsx, extract_source_url_ts, extract_tooltips,
)
from .fetch import classify, fetch_all
from .models import DetailTemplate, LinkRow
from .normalize import normalize_url
from .sample import (
    DETAIL_TEMPLATE_LAYERS, LAYER_ENDPOINT_PARAMS,
    LAYER_ENDPOINTS, STORED_URL_LAYERS, build_deep_link, build_detail_link,
    fetch_layer_features, group_stored_urls, prefix_row,
)

# ── Known-unwalked surfaces (disclosure, not extraction) ────────────────────
#
# These files carry real user/bot-facing source URLs but have no extractor.
# Per the binding constraint ("coverage gaps appear in the report body, never
# as absence"), each is disclosed as an explicit `not_checked` entry rather
# than silently omitted from `manifest rows` / `unique urls`. Building real
# extractors for these is deferred follow-up scope.
#
# DetailPanel.tsx and SEO.tsx gained real extractors on 2026-07-25 and are no
# longer listed here.
#
# `frontend/seo/render-page.js` was listed as "~10 bot-facing SEO citations".
# That was WRONG, and measuring it is what showed why: all 21 of its URLs point
# at something-rare.com. It cites nothing external. Worse, `frontend/server.js`
# ends in a catch-all `app.get('*')` serving the SPA shell for every path, so
# each one returns 200 regardless of whether the route exists — auditing them
# would manufacture green, not coverage. It is excluded by SELF_HOSTS, not
# deferred, and no extractor is owed for it.
UNWALKED_SURFACES: list[tuple[str, int, str]] = []


def unwalked_surface_entries() -> list[str]:
    """One `not_checked` disclosure line per `UNWALKED_SURFACES` entry."""
    return [
        f"{path}: ~{count} source URLs NOT EXTRACTED — {reason}; "
        f"its links are absent from this run"
        for path, count, reason in UNWALKED_SURFACES
    ]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# DetailPanel.tsx was split (2026-08) into ~65 per-family panel components
# under frontend/src/components/panels/**/*.tsx; the root file kept only the
# dispatcher. Globbing keeps a future 7th domain directory covered without
# another hardcoded path edit here.
def _detail_panel_files(repo: Path) -> list[Path]:
    root = repo / "frontend/src/components/DetailPanel.tsx"
    globbed = sorted(
        Path(p) for p in glob.glob(
            str(repo / "frontend/src/components/panels/**/*.tsx"), recursive=True)
    )
    return [root, *globbed]


# Map3DControls.tsx's LAYER_TOOLTIPS_META moved entirely into
# controls/tooltips.ts as part of the same split; glob controls/** (not just
# that one file) so a future relocation of the table stays covered.
def _controls_tooltip_files(repo: Path) -> list[Path]:
    return sorted(
        Path(p) for p in glob.glob(
            str(repo / "frontend/src/components/controls/**/*.ts*"), recursive=True)
    )


def collect_static_rows(repo: Path) -> list[LinkRow]:
    su = repo / "frontend/src/utils/sourceUrl.ts"
    lp = repo / "frontend/src/components/LegendPanel.tsx"
    mn = repo / "backend/main.py"
    er = repo / "backend/services/export_registry.py"
    seo = repo / "frontend/src/components/SEO.tsx"

    rows: list[LinkRow] = []
    rows += extract_source_url_ts(_read(su), str(su.relative_to(repo)))
    for p in _controls_tooltip_files(repo):
        rows += extract_tooltips(_read(p), str(p.relative_to(repo)))
    rows += extract_legend_tsx(_read(lp), str(lp.relative_to(repo)))
    rows += extract_inventory(_read(mn), str(mn.relative_to(repo)))
    rows += extract_provenance(_read(er), str(er.relative_to(repo)))
    for p in _detail_panel_files(repo):
        rows += extract_detail_panel(_read(p), str(p.relative_to(repo)))[0]
    rows += extract_seo_tsx(_read(seo), str(seo.relative_to(repo)))

    for path in sorted(glob.glob(str(repo / "frontend/public/locales/*/legend.json"))):
        p = Path(path)
        rows += extract_locale_urls(
            json.loads(_read(p)), p.parent.name, str(p.relative_to(repo)))
    return rows


def prefix_only_urls(rows: list[LinkRow]) -> set[str]:
    """URLs that are ONLY ever fetched as a template's static prefix.

    A prefix is an incomplete URL by construction, so a 404 on it carries no
    information: `https://doi.pangaea.de/10.1594/` is a DOI stem missing its
    suffix, and `https://explore.openaq.org/locations/` is a station page
    missing its station. Both 404 while the host is perfectly healthy.

    A URL that ALSO appears on a real surface is excluded — there the 404 is
    about a link the product genuinely renders.
    """
    prefix = {r.url_normalized for r in rows if r.surface == "detail-prefix"}
    real = {r.url_normalized for r in rows if r.surface != "detail-prefix"}
    return prefix - real


def downgrade_prefix_only_dead(
    verdict: str, url: str, prefix_only: set[str]
) -> str:
    """A DEAD verdict on a prefix-only URL is an artefact, not a finding.

    Downgraded to NOT_CHECKED — the rubric's own category for "this was not
    really checked" — so it lands in the coverage-gap section instead of the
    needs-a-decision one. Reporting it as DEAD would send the maintainer to
    replace a citation that is not broken, which is worse than not checking.

    OK / REDIRECT_OK on a prefix survives untouched: a live path root IS
    evidence the host and route still exist.
    """
    if verdict in ("DEAD", "CHANGED_MEANING") and url in prefix_only:
        return "NOT_CHECKED"
    return verdict


def collect_detail_templates(repo: Path) -> list[DetailTemplate]:
    templates: list[DetailTemplate] = []
    for p in _detail_panel_files(repo):
        templates += extract_detail_panel(_read(p), str(p.relative_to(repo)))[1]
    return templates


def collect_locale_divergence(repo: Path) -> list[dict]:
    by_locale: dict[str, list[LinkRow]] = {}
    for path in sorted(glob.glob(str(repo / "frontend/public/locales/*/legend.json"))):
        p = Path(path)
        by_locale[p.parent.name] = extract_locale_urls(
            json.loads(_read(p)), p.parent.name, str(p.relative_to(repo)))
    return find_locale_divergence(by_locale)


def dedupe_for_fetch(rows: list[LinkRow]) -> list[str]:
    """One fetch per unique normalized URL; every occurrence still reported."""
    return list(dict.fromkeys(r.url_normalized for r in rows))


async def collect_sampled_rows(
    templates: list, api_key: str,
    detail_templates: list[DetailTemplate] | None = None,
) -> tuple[list[LinkRow], dict[str, dict[str, int]], list[str]]:
    """Sample live features to build deep-link rows (B1) and stored-URL rows (B2).

    Returns (rows, {layer: {host: total_seen}}, not_checked_reasons).
    """
    rows: list[LinkRow] = []
    group_sizes: dict[str, dict[str, int]] = {}
    not_checked: list[str] = []

    for tpl in templates:
        endpoint = LAYER_ENDPOINTS.get(tpl.key)
        if not endpoint:
            not_checked.append(f"{tpl.key}: no sampling endpoint configured")
            continue
        feats = await fetch_layer_features(
            endpoint, api_key=api_key, limit=5,
            params=LAYER_ENDPOINT_PARAMS.get(tpl.key),
        )
        if not feats:
            not_checked.append(f"{tpl.key}: endpoint returned no features ({endpoint})")
            continue

        # B1 — generated deep-links.
        built = None
        for feat in feats:
            built = build_deep_link(tpl, feat.get("properties") or {})
            if built:
                break
        if built:
            rows.append(LinkRow(
                layer_id=tpl.key, surface="deep-link", url_raw=built,
                url_normalized=normalize_url(built), kind="deep-link",
                file=f"api:{endpoint}", line=0,
            ))
        else:
            not_checked.append(
                f"{tpl.key}: no sampled feature carried {list(tpl.props)} "
                f"— builder falls back to homepage by design")

        # B2 — URLs stored on the rows themselves.
        stored, sizes = group_stored_urls(feats, tpl.key, f"api:{endpoint}")
        rows.extend(stored)
        if sizes:
            group_sizes[tpl.key] = sizes

    # B2b — layers with no perFeature deep-link template at all, visited
    # purely for their stored per-row URLs. Same disclosure discipline as the
    # loop above: a dead endpoint or a feature set with no stored URLs still
    # lands in `not_checked`, it is never silently absent from the report.
    for layer_id, (endpoint, params) in STORED_URL_LAYERS.items():
        feats = await fetch_layer_features(endpoint, api_key=api_key, limit=5, params=params)
        if not feats:
            not_checked.append(
                f"{layer_id}: endpoint returned no features ({endpoint})")
            continue

        stored, sizes = group_stored_urls(feats, layer_id, f"api:{endpoint}")
        rows.extend(stored)
        if sizes:
            group_sizes[layer_id] = sizes
        else:
            not_checked.append(
                f"{layer_id}: sampled features carried no stored URL props "
                f"({endpoint})")

    # B3 — DetailPanel.tsx `${…}` templates. A mapped template is built from a
    # real sampled feature; an unmapped one (or one whose property is absent on
    # every sampled feature) falls back to its static prefix. The fallback is
    # weaker on purpose and is disclosed below — it catches a dead host or a
    # moved path root, never a bad id.
    feature_cache: dict[str, list[dict]] = {}
    prefix_only = 0

    for tpl in detail_templates or []:
        entry = DETAIL_TEMPLATE_LAYERS.get(tpl.prefix)
        if entry is None:
            rows.append(prefix_row(tpl))
            prefix_only += 1
            continue

        layer_id, endpoint, params, prop = entry
        if endpoint not in feature_cache:
            feature_cache[endpoint] = await fetch_layer_features(
                endpoint, api_key=api_key, limit=5, params=params)
        feats = feature_cache[endpoint]

        built = None
        for feat in feats:
            built = build_detail_link(tpl, feat.get("properties") or {})
            if built:
                break

        if built:
            rows.append(LinkRow(
                layer_id=layer_id, surface="detail-deep-link", url_raw=built,
                url_normalized=normalize_url(built), kind="deep-link",
                file=tpl.file, line=tpl.line,
            ))
        else:
            rows.append(prefix_row(tpl))
            prefix_only += 1
            not_checked.append(
                f"{layer_id}: no sampled feature carried '{prop}' — "
                f"{tpl.prefix} checked at its static prefix only "
                f"({tpl.file}:{tpl.line})")

    if prefix_only:
        not_checked.append(
            f"{prefix_only} DetailPanel.tsx template(s) checked at their static "
            f"prefix only: a dead host or moved path root IS detected, a broken "
            f"per-feature id is NOT. Unmapped by design — see "
            f"DETAIL_TEMPLATE_LAYERS for which templates carry no single "
            f"substitutable feature property.")

    return rows, group_sizes, not_checked


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default="/tmp/link-audit")
    ap.add_argument("--no-sample", action="store_true",
                    help="skip the live per-feature planes even if a key is set")
    args = ap.parse_args(argv)

    repo, out = Path(args.repo).resolve(), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = collect_static_rows(repo)
    templates = extract_deep_link_templates(_read(repo / "frontend/src/utils/sourceUrl.ts"))
    detail_templates = collect_detail_templates(repo)
    divergence = collect_locale_divergence(repo)

    # ── Plane B: live sampling (degrades loudly, never silently) ──────────────
    api_key = os.environ.get("ABYSSAL_API_KEY", "")
    group_sizes: dict[str, dict[str, int]] = {}
    not_checked: list[str] = []
    if args.no_sample or not api_key:
        not_checked.append(
            "per-feature planes skipped (--no-sample)" if args.no_sample else
            "per-feature planes NOT CHECKED — ABYSSAL_API_KEY unset. "
            "Deep-link and stored-URL coverage is absent from this run.")
        # The DetailPanel prefix check is static — it needs no key, so it still
        # runs. Degrading to "no coverage at all" here would hide a dead host
        # behind a missing credential.
        rows.extend(prefix_row(t) for t in detail_templates)
        not_checked.append(
            f"{len(detail_templates)} DetailPanel.tsx template(s) checked at "
            f"their static prefix only — no key, so no feature was available to "
            f"substitute. Host/path-root death IS detected; a broken id is NOT.")
    else:
        sampled, group_sizes, sampled_not_checked = asyncio.run(
            collect_sampled_rows(templates, api_key, detail_templates))
        rows.extend(sampled)
        not_checked.extend(sampled_not_checked)

    # Always disclosed, regardless of which branch above ran — these are
    # known-unwalked surfaces, not sampling-outage artifacts.
    not_checked.extend(unwalked_surface_entries())

    (out / "link-manifest.json").write_text(json.dumps({
        "rows": [r.to_dict() for r in rows],
        "deep_link_templates": [asdict(t) for t in templates],
        "locale_divergence": divergence,
        "stored_group_sizes": group_sizes,
        "not_checked": not_checked,
    }, indent=2), encoding="utf-8")

    urls = dedupe_for_fetch(rows)
    results = asyncio.run(fetch_all(urls))

    prefix_only = prefix_only_urls(rows)
    scored = []
    for res in results:
        verdict = classify(res)
        final = downgrade_prefix_only_dead(verdict, res.url, prefix_only)
        if final != verdict:
            not_checked.append(
                f"{res.url}: HTTP {res.status} on a template PREFIX, which is an "
                f"incomplete URL by construction — inconclusive, not a dead link. "
                f"The per-feature URL built from it was never checked.")
        scored.append({**asdict(res), "verdict": final})

    (out / "link-results.json").write_text(
        json.dumps(scored, indent=2), encoding="utf-8")

    # Rewrite the manifest so its not_checked matches the scored results —
    # the downgrades above are only known after fetching.
    (out / "link-manifest.json").write_text(json.dumps({
        "rows": [r.to_dict() for r in rows],
        "deep_link_templates": [asdict(t) for t in templates],
        "locale_divergence": divergence,
        "stored_group_sizes": group_sizes,
        "not_checked": not_checked,
    }, indent=2), encoding="utf-8")

    print(f"manifest rows: {len(rows)}  unique urls: {len(urls)}  "
          f"locale divergences: {len(divergence)}  not-checked: {len(not_checked)}")
    for reason in not_checked:
        print(f"  NOT CHECKED — {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
