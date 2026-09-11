# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The docs that ship to the PUBLIC MIRROR must not contradict the code.

`scripts/export-public.sh` exports by allowlist. Of the documentation, exactly
these reach the public repository: README.md, DATA-LICENCES.md, NOTICE,
CITATION.cff, .zenodo.json, CONTRIBUTING.md, SECURITY.md, COMMERCIAL.md, the
licences, and everything under docs/methods/. A false claim in one of those is
published, forked and cached — `docs/audits/` is private and gets no such reach.

Three claims went stale without anything noticing, which is why this file exists:

  * README.md said "the platform never alters or derives source values" while
    docs/methods/data-passthrough.md — same repository, same export — listed
    three model layers and a noise normalisation it performs.
  * DATA-LICENCES.md carried one row, "GEBCO 2024", while three different GEBCO
    products are served on purpose: the GEBCO_LATEST relief WMS (GEBCO_2026 as
    of 2026-09-08), the GEBCO_2024 confidence/TID grid, and a GEBCO_2020 point
    lookup.
  * data-passthrough.md listed air-quality units as a known gap for months
    after the sync started reading, storing and serving them.

⛔ Comments are stripped before every scan. Five guards in this suite have gone
red on their own explanatory prose — including the gebcoTiles.ts comment that
tells the GEBCO_2025 story and would otherwise demand a licence row for a
vintage we deliberately stopped serving.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _strip_py(text: str) -> str:
    """Comments and docstrings out; executable Python in."""
    try:
        tree = ast.parse(text)
    except SyntaxError:  # pragma: no cover - a broken file is another test's problem
        return text
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body.pop(0)
    return ast.unparse(tree)


def _strip_ts(text: str) -> str:
    """`/* … */` and `// …` out; executable TypeScript in."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"(?<!:)//[^\n]*", " ", text)


# ── 1. The platform's own derivations ───────────────────────────────────────

def test_readme_does_not_deny_the_derivations_its_own_methods_note_lists():
    readme = (ROOT / "README.md").read_text()
    passthrough = (ROOT / "docs" / "methods" / "data-passthrough.md").read_text()

    # The methods note is the authority: if it lists derived products, the
    # README may not tell a reader that nothing is ever derived.
    assert "Derived products are labelled" in passthrough, \
        "data-passthrough.md no longer lists derived products — re-anchor this guard"

    denials = [
        "never alters or derives",
        "never derives",
        "does not derive",
        "no derived values",
        "nothing is derived",
    ]
    hit = [d for d in denials if d in readme.lower()]
    assert not hit, (
        f"README.md claims {hit} while docs/methods/data-passthrough.md lists "
        "layers and fields this platform derives. Both files ship to the public mirror."
    )


def test_every_derivation_the_methods_note_discloses_is_real():
    """A disclosure that names something we do not do is as wrong as a denial."""
    passthrough = (ROOT / "docs" / "methods" / "data-passthrough.md").read_text()

    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    from startup_seeds import LAYER_DEFAULTS_PY  # noqa: E402

    layer_ids = {d["id"] for d in LAYER_DEFAULTS_PY}
    for layer in ("vme-suitability", "coral-acid-exposure", "noise-risk"):
        assert layer in passthrough, f"{layer} dropped out of the derived-products list"
        assert layer in layer_ids, f"{layer} is disclosed as derived but is not a served layer"

    # The field-level disclosure: chess.habitat_type and its fallback.
    assert "chess.habitat_type" in passthrough, \
        "the chess habitat classification is ours and the methods note must say so"
    chess = _strip_py((ROOT / "backend" / "ingestion" / "chess_ingest.py").read_text())
    assert "unclassified" in chess, \
        "the note promises an `unclassified` fallback the ingest no longer produces"
    assert '"omz"' not in chess and "'omz'" not in chess, \
        "the omz fallback is back: it labelled 97.0% of the layer with a habitat " \
        "the classifier cannot detect"


# ── 2. GEBCO: every vintage we serve is on the licence map ──────────────────

_GEBCO_SOURCES = (
    Path("frontend/src/utils/gebcoTiles.ts"),
    Path("backend/domains/seafloor.py"),
    Path("backend/main.py"),
)


def test_every_gebco_vintage_in_the_code_appears_in_the_public_licence_map():
    licences = (ROOT / "DATA-LICENCES.md").read_text()

    found: dict[str, str] = {}
    for rel in _GEBCO_SOURCES:
        raw = (ROOT / rel).read_text()
        code = _strip_ts(raw) if rel.suffix == ".ts" else _strip_py(raw)
        for m in re.findall(r"GEBCO_(?:LATEST|\d{4})", code):
            found.setdefault(m, str(rel))

    assert found, "no GEBCO product found in the code — this guard has lost its subject"

    missing = {v: f for v, f in found.items() if v not in licences}
    assert not missing, (
        f"served but absent from DATA-LICENCES.md: {missing}. The file shipped one "
        "'GEBCO 2024' row while three different vintages were on the map."
    )


# ── 3. Known gaps that are no longer gaps ──────────────────────────────────

def test_the_air_quality_unit_gap_is_not_claimed_while_the_code_fills_it():
    hazards = _strip_py((ROOT / "backend" / "domains" / "land" / "hazards.py").read_text())
    reads_units = 'param.get("units")' in hazards or "param.get('units')" in hazards

    passthrough = (ROOT / "docs" / "methods" / "data-passthrough.md").read_text()
    claims_gap = "does not currently request that field" in passthrough

    assert not (reads_units and claims_gap), (
        "hazards.py reads OpenAQ's per-sensor unit while docs/methods/data-passthrough.md "
        "still tells the public we do not. The doc ships; the reader believes it."
    )
    assert reads_units or claims_gap, (
        "the ingest stopped reading OpenAQ units and the methods note does not say so — "
        "a silent regression in the opposite direction."
    )


# ── 4. Every served layer is reachable from the public licence map ─────────

def test_every_served_layer_appears_in_the_public_licence_map():
    """`dams` shipped for months with no licence row at all — in neither the
    licensed rows nor the honest "under review" bucket. Nothing noticed, because
    most rows named their layer in PROSE ("ocean currents", "climatology") and a
    reader looking one up by id found nothing. Rows now carry the backticked id,
    and this guard keeps them carrying it.

    A layer with no resolvable licence is NOT a failure of this test — the file
    has a deliberate `_(under review)_` row that says so in public. Being in
    NEITHER place is the failure: that is the state `dams` was in.
    """
    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    from startup_seeds import LAYER_DEFAULTS_PY  # noqa: E402

    licences = (ROOT / "DATA-LICENCES.md").read_text()
    ids = sorted({d["id"] for d in LAYER_DEFAULTS_PY})
    assert len(ids) > 40, f"only {len(ids)} layers in the registry — re-anchor this guard"

    missing = [i for i in ids if f"`{i}`" not in licences]
    assert not missing, (
        f"{len(missing)} served layer(s) absent from DATA-LICENCES.md: {missing}. "
        "The file ships to the public mirror; a layer missing from it is "
        "indistinguishable from a layer with no restrictions."
    )


def test_the_non_commercial_dependencies_are_both_named():
    """CLAUDE.md's inviolable rule names ONE non-commercial lineage. Reading
    OceanOPS's own terms on 2026-09-11 found a second: the `oceansites` feed is
    "educational and other non-commercial purposes" with "all rights reserved".
    Both must stay visible, because the monetisation question is decided by the
    STRICTEST term, not by the best-known one.
    """
    licences = (ROOT / "DATA-LICENCES.md").read_text()

    assert "CC-BY-NC 4.0" in licences and "seabed-substrate" in licences, \
        "the Dutkiewicz CC-BY-NC lineage lost its row or its served layer id"
    assert "non-commercial purposes" in licences and "`oceansites`" in licences, \
        "the OceanOPS non-commercial clause is no longer recorded against `oceansites`"
