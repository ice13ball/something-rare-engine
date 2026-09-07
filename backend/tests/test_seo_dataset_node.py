# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The `isPartOf` Dataset node on every SSR entity page must stay valid.

Google's structured-data spec makes `description` a *required* property of
`Dataset`. It was missing from all six of `domains/seo.py`'s hand-copied
`isPartOf` literals, so Search Console rejected 2,028 items across
`/concession/*`, `/vent/*`, `/seamount/*`, `/oceansites/*`, `/onc/*` and
`/resource/*` simultaneously — one absent key, six broken page types, because
there was no single place to add it.

These tests lock the shape of the fix rather than the symptom:

* `test_no_inline_ispartof_literal` is the one that matters. It walks the AST
  and fails if any `isPartOf` is spelled as a dict literal instead of a
  reference to `ABYSSAL_DATASET`. A seventh entity route that copy-pastes the
  old block fails here — which is what iterating "the six routes" was meant to
  achieve, without needing a live database to do it.
* `test_description_matches_site_graph` guards the other half: the string is
  duplicated across a language boundary (Python constant vs. the JSON the
  frontend ships), and both land in the *same* rendered document. Asserting
  equality is cheaper than trusting anyone to edit two files at once.

`test_site_graph_datasets_have_description` is a regression check on the 11
`isBasedOn` source datasets. They were never broken; anyone grepping
`site-graph.json` during the incident would have concluded the site was
healthy. This test exists so that conclusion stays true.
"""

import ast
import json
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
SEO_PY = BACKEND / "domains" / "seo.py"
SITE_GRAPH = REPO / "frontend" / "seo" / "site-graph.json"

# Every SSR entity route that hangs a page off the shared Dataset node. Kept as
# documentation of blast radius; the AST test below is what actually enforces
# coverage, and it needs no list to keep up to date.
SSR_ENTITY_ENDPOINTS = (
    "seo_concession",
    "seo_vent",
    "seo_seamount",
    "seo_oceansites",
    "seo_onc",
    "seo_resource",
)


def _site_graph() -> dict:
    return json.loads(SITE_GRAPH.read_text(encoding="utf-8"))


def _ispartof_values() -> list[tuple[int, ast.AST]]:
    """Every `"isPartOf": <value>` in seo.py, as (line number, value node)."""
    tree = ast.parse(SEO_PY.read_text(encoding="utf-8"))
    found: list[tuple[int, ast.AST]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if isinstance(key, ast.Constant) and key.value == "isPartOf":
                found.append((key.lineno, value))
    return found


def test_dataset_node_has_required_fields():
    from domains.seo import ABYSSAL_DATASET

    assert ABYSSAL_DATASET["@type"] == "Dataset"
    # name + description are the two Google actually requires.
    for field in ("name", "description"):
        value = ABYSSAL_DATASET.get(field)
        assert isinstance(value, str) and value.strip(), (
            f"Dataset.{field} is required by Google's structured-data spec; "
            "omitting it rejects the whole node, not just the field"
        )


def test_description_matches_site_graph():
    """The Python constant and the shipped JSON must not drift apart.

    Both appear in one rendered SSR document (`render-page.js` emits the
    per-page JSON-LD and the full site graph), so two different sentences would
    have the site describing itself two ways on the same page.
    """
    from domains.seo import ABYSSAL_DATASET

    web_app = [n for n in _site_graph()["@graph"] if n.get("@type") == "WebApplication"]
    assert len(web_app) == 1, "expected exactly one WebApplication node in site-graph.json"

    assert ABYSSAL_DATASET["description"] == web_app[0]["description"], (
        "domains/seo.py ABYSSAL_DATASET['description'] has drifted from "
        "frontend/seo/site-graph.json @graph WebApplication.description — "
        "edit both or neither"
    )


def test_no_inline_ispartof_literal():
    """No `isPartOf` may be a dict literal — the defect was six of them."""
    values = _ispartof_values()
    assert len(values) >= len(SSR_ENTITY_ENDPOINTS), (
        f"expected at least {len(SSR_ENTITY_ENDPOINTS)} isPartOf sites in "
        f"seo.py, found {len(values)} — did a route lose its Dataset node?"
    )

    inline = [
        lineno for lineno, value in values if not isinstance(value, ast.Name)
    ]
    assert not inline, (
        "isPartOf must reference the shared ABYSSAL_DATASET constant, never an "
        f"inline dict. Offending lines in domains/seo.py: {inline}. "
        "A hand-copied literal is how `description` came to be missing from "
        "six page types at once."
    )

    wrong_name = [
        (lineno, value.id)
        for lineno, value in values
        if isinstance(value, ast.Name) and value.id != "ABYSSAL_DATASET"
    ]
    assert not wrong_name, f"isPartOf bound to an unexpected name: {wrong_name}"


@pytest.mark.skipif(not SITE_GRAPH.exists(), reason="site-graph.json not present")
def test_site_graph_datasets_have_description():
    """Regression guard on the `isBasedOn` source datasets — never broken."""

    def walk(node, path="@graph"):
        if isinstance(node, dict):
            if node.get("@type") == "Dataset":
                desc = node.get("description")
                assert isinstance(desc, str) and desc.strip(), (
                    f"Dataset without description at {path}: "
                    f"{node.get('name', '<unnamed>')}"
                )
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(_site_graph())
