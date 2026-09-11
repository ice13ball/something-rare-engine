# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""`habitat_type` is our derivation, and its fallback must not read as a finding.

ChEssBase via GBIF ships a free-text locality. `classify_habitat` matches three
patterns against it — whale-fall, seep, vent — and everything else fell through
to `"omz"`, which reads as a positive result: an oxygen-minimum-zone community.

It never was one. There is no OMZ pattern in the classifier at all, so "omz"
only ever meant "none of my three keywords matched". Measured on production
2026-09-10:

    omz         3,605 of 3,715  (97.0%)
    vent           80
    seep           16
    whale_fall     14
    records with an empty locality: 0

So all 3,605 came from the fallback, and 97% of the layer was labelled with a
habitat we never detected — in the API and Area Export as well as the panel.
Same rule as everywhere else this week: "missing" and "broken" must not share a
code path, and a value we derived must not be presented as the source's own.

⛔ The value set is READ from the ingest. Renaming or adding a habitat type
must fail here until every label, colour and weight map has been updated —
including two weight maps used in scoring, where a missed key would silently
become `undefined` and change a ranking.
"""
import ast
import pathlib
import re

ROOT   = pathlib.Path(__file__).resolve().parents[1]
INGEST = ROOT / "ingestion" / "chess_ingest.py"
FRONT  = ROOT.parent / "frontend"
LOCALES = FRONT / "public" / "locales"

#: Every file that maps a habitat value to a label, colour or weight.
CONSUMERS = [
    "src/components/panels/ocean/ChessPanel.tsx",
    "src/components/ChessReport.tsx",
    "src/styles/colorStandards.ts",
    "src/components/Map3D.tsx",
    "src/components/ClaimReport.tsx",
    "src/components/SearchBar.tsx",
    "src/components/panels/ocean/MiningPanel.tsx",
]


def _habitat_types() -> tuple[str, ...]:
    tree = ast.parse(INGEST.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", "") == "HABITAT_TYPES" for t in node.targets):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("fixture problem: HABITAT_TYPES did not parse")


def _returns() -> set[str]:
    """Every literal `classify_habitat` can actually return."""
    tree = ast.parse(INGEST.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "classify_habitat")
    return {n.value.value for n in ast.walk(fn)
            if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)}


def test_the_declared_set_matches_what_the_function_returns():
    # ⛔ A declared list that drifts from the code is worse than no list: every
    # consumer check below would then be validating against a fiction.
    assert _returns() == set(_habitat_types()), (
        f"HABITAT_TYPES says {sorted(_habitat_types())} but classify_habitat "
        f"returns {sorted(_returns())}"
    )


def test_the_fallback_does_not_name_a_habitat_we_never_detect():
    types = _returns()
    assert "omz" not in types, (
        "the classifier returns 'omz' again. There is no OMZ pattern in it — "
        "that value only ever meant 'no keyword matched', and it carried 97% "
        "of the layer"
    )
    assert "unclassified" in types, "there is no honest fallback value at all"


def _strip_comments(src: str) -> str:
    """Drop // and /* */ comments.

    ⛔ Five guards this week first reddened on, or were fooled by, the
    assistant's own prose. Here a comment reading "`unclassified` keeps the
    weight `omz` had" made a whole-file search see both values in a file whose
    MAP had neither, and two sabotages sailed through.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(ln.split("//")[0] for ln in src.splitlines())


#: Every `{ ... }` object literal that keys on a habitat value.
_MAP = re.compile(r"Record<string,\s*(?:string|number)>\s*=\s*\{([^}]*)\}")


def test_the_fixture_finds_the_maps_it_is_meant_to_check():
    found = {rel: len(_MAP.findall(_strip_comments((FRONT / rel).read_text(encoding="utf-8"))))
             for rel in CONSUMERS}
    # MiningPanel alone holds two — a weight map and a label map, 16 lines
    # apart. A per-FILE check missed the second one entirely.
    assert found["src/components/panels/ocean/MiningPanel.tsx"] >= 2, found
    assert sum(found.values()) >= 6, f"fixture problem: only found {found}"


def test_every_habitat_map_handles_every_value_the_classifier_can_return():
    types = {t for t in _returns() if t != "vent"}   # vent is never a map dot
    missing = {}
    for rel in CONSUMERS:
        code = _strip_comments((FRONT / rel).read_text(encoding="utf-8"))
        for i, body in enumerate(_MAP.findall(code)):
            # Only maps that already key on a habitat value are ours to check.
            if not any(re.search(rf"\b{t}\s*:", body) for t in types | {"omz", "seep", "whale_fall"}):
                continue
            gone = [t for t in types if not re.search(rf"\b{t}\s*:", body)]
            if gone:
                missing[f"{rel}#{i}"] = gone
    assert not missing, (
        f"these habitat maps do not handle {missing}. A missed key in a weight "
        "map becomes undefined and changes a ranking silently — MiningPanel's "
        "second map was labelling 97% of the layer 'OMZ' unnoticed."
    )


def test_the_legacy_value_still_renders_while_the_table_turns_over():
    # Rows ingested before 2026-09-11 still hold 'omz'. Dropping the key would
    # blank them until the next sync rewrites every row.
    for rel in ("src/components/panels/ocean/ChessPanel.tsx",
                "src/components/Map3D.tsx",
                "src/components/panels/ocean/MiningPanel.tsx"):
        src = (FRONT / rel).read_text(encoding="utf-8")
        assert re.search(r"\bomz\b", src), (
            f"{rel} no longer handles the legacy 'omz' value; existing rows "
            "would render unstyled or unweighted until the next full sync"
        )


def test_every_locale_says_the_classification_is_ours():
    missing = []
    for loc in sorted(p for p in LOCALES.iterdir() if (p / "legend.json").is_file()):
        import json
        d = json.loads((loc / "legend.json").read_text(encoding="utf-8"))
        text = str(d.get("verify", {}).get("chess", ""))
        if "habitat_type" not in text:
            missing.append(loc.name)
    assert not missing, (
        f"{missing} do not tell the reader that habitat_type is our own keyword "
        "classification rather than a ChEssBase field"
    )
