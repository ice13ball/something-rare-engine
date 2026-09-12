# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""LAYER_DEFAULTS (TS), LAYER_DEFAULTS_PY (Python) and LAYER_OPS must agree.

No compiler spans TypeScript and Python, so the KEEP IN SYNC comment on each
registry is the only thing holding them together. Two layers once drifted out
of both at the same time and fell back to order_idx 9999, drawing above
everything else.

This reads source text on purpose for the TS side: the rule is about what the
file DECLARES, not about what any function returns. Both `//` and `/* */`
comments are stripped before parsing — a layer id or order_idx mentioned only
in prose (a justification comment, a TODO) must never be mistaken for a real
registry entry. This is not theoretical: a 26-vs-25 identifier count was once
produced by counting a layer name that only appeared in a comment.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_TS = _REPO / "frontend" / "src" / "utils" / "layerConfig.ts"
_PY = _REPO / "backend" / "startup_seeds.py"


def _strip_ts_comments(text: str) -> str:
    """Remove `//` line comments and `/* */` block comments from TS source.

    Deliberately simple (no string-literal awareness) — layerConfig.ts does not
    put `//` or `/*` inside its string literals, and a test that reads source
    text should stay as legible as the thing it's checking.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _strip_py_comments(text: str) -> str:
    """Remove `#` comments from Python source (line-oriented, no string awareness
    needed for the same reason as the TS side: no `#` appears inside a literal
    in startup_seeds.py's LAYER_DEFAULTS_PY block)."""
    return re.sub(r"#[^\n]*", "", text)


def _ts_defaults() -> dict[str, int]:
    """Parse `{ id: "x", order_idx: N, ... }` entries out of LAYER_DEFAULTS,
    with comments stripped first so a layer id or order_idx mentioned only in
    a comment can never be counted as a real entry."""
    text = _strip_ts_comments(_TS.read_text(encoding="utf-8"))
    start = text.index("export const LAYER_DEFAULTS")
    end = text.index("];", start)
    block = text[start:end]
    return {
        m.group("id"): int(m.group("idx"))
        for m in re.finditer(
            r'id:\s*"(?P<id>[a-z0-9-]+)"\s*,\s*order_idx:\s*(?P<idx>\d+)', block
        )
    }


def _py_defaults() -> dict[str, int]:
    from startup_seeds import LAYER_DEFAULTS_PY

    return {d["id"]: d["order_idx"] for d in LAYER_DEFAULTS_PY}


def _layer_ops_ids() -> set[str]:
    from layer_ops import LAYER_OPS

    return set(LAYER_OPS.keys())


def test_the_two_registries_list_the_same_layers():
    ts, py = _ts_defaults(), _py_defaults()
    assert ts, "parsed zero entries from LAYER_DEFAULTS - the parser is broken, not the data"
    assert sorted(ts) == sorted(py), (
        f"only in TS: {sorted(set(ts) - set(py))}; only in Python: {sorted(set(py) - set(ts))}"
    )


def test_order_idx_agrees_for_every_layer():
    ts, py = _ts_defaults(), _py_defaults()
    mismatched = {k: (ts[k], py[k]) for k in ts.keys() & py.keys() if ts[k] != py[k]}
    assert not mismatched, f"order_idx differs (ts, py): {mismatched}"


def test_a_comment_mentioning_a_fake_layer_or_order_idx_is_ignored():
    """Guard the guard: comments must not be able to satisfy this test.

    If either stripper regresses, a stray justification comment naming a layer
    id or an order_idx could silently inflate or corrupt the parsed set. This
    injects exactly that shape of comment (in memory, not on disk) and checks
    the parser does not pick it up.
    """
    real_ts = _TS.read_text(encoding="utf-8")
    poisoned_ts = real_ts.replace(
        "export const LAYER_DEFAULTS",
        '// id: "totally-fake-layer", order_idx: 9999,\n'
        "export const LAYER_DEFAULTS",
        1,
    )
    stripped = _strip_ts_comments(poisoned_ts)
    start = stripped.index("export const LAYER_DEFAULTS")
    end = stripped.index("];", start)
    block = stripped[start:end]
    parsed_ids = {
        m.group("id")
        for m in re.finditer(
            r'id:\s*"(?P<id>[a-z0-9-]+)"\s*,\s*order_idx:\s*(?P<idx>\d+)', block
        )
    }
    assert "totally-fake-layer" not in parsed_ids


def test_layer_ops_covers_the_same_set_of_layers():
    """LAYER_OPS (backend/layer_ops.py) must cover exactly the same layer ids
    as the two default registries. A missing entry here doesn't fail loudly —
    it silently reports 'unknown' health and cannot be purged, and (per task 1)
    a wrong log_source breaks the "ran and found nothing" vs "never ran"
    distinction without any test noticing."""
    ts = _ts_defaults()
    ops = _layer_ops_ids()
    assert ts, "parsed zero entries from LAYER_DEFAULTS - the parser is broken, not the data"
    assert sorted(ts) == sorted(ops), (
        f"only in LAYER_DEFAULTS: {sorted(set(ts) - set(ops))}; "
        f"only in LAYER_OPS: {sorted(set(ops) - set(ts))}"
    )


# ── The export registries, which nothing held to anything ────────────────────
#
# `backend/services/export_registry.py` decides what the Area Export API will
# serve; `frontend/src/utils/exportLayers.ts` decides what the export panel
# OFFERS. Neither was compared against the other or against the layer
# registries above, and the failure is silent in both directions: a backend
# entry with no frontend entry is a download nobody can reach, and a frontend
# entry with no backend entry is a button that 404s.

_FE_EXPORTS = _REPO / "frontend" / "src" / "utils" / "exportLayers.ts"


def _fe_export_ids() -> dict[str, str]:
    """`id` -> `mapLayerId or id` for every EXPORT_LAYERS_FE entry.

    Comments are stripped first, for the same reason the layer parser above does
    it: an id that appears only in a justification comment must never count as a
    registry entry.
    """
    text = _strip_ts_comments(_FE_EXPORTS.read_text(encoding="utf-8"))
    start = text.index("export const EXPORT_LAYERS_FE")
    block = text[start:]
    out: dict[str, str] = {}
    for m in re.finditer(
        r'\{\s*id:\s*"(?P<id>[a-z0-9-]+)"(?P<rest>.*?)\}', block, flags=re.DOTALL
    ):
        mapped = re.search(r'mapLayerId:\s*"([a-z0-9-]+)"', m.group("rest"))
        out[m.group("id")] = mapped.group(1) if mapped else m.group("id")
    return out


def _be_export_ids() -> set[str]:
    from services.export_registry import EXPORT_LAYERS

    return set(EXPORT_LAYERS.keys())


def _composite_member_ids() -> set[str]:
    """Ids that exist only as members of a CompositeExport.

    These are correctly absent from the panel: the user picks the composite
    ("Submarine Cables"), and the ZIP carries one file per member. Listing them
    separately would offer six buttons for one download.
    """
    from services.export_registry import EXPORT_LAYERS, CompositeExport

    members: set[str] = set()
    for entry in EXPORT_LAYERS.values():
        if isinstance(entry, CompositeExport):
            members.update(entry.members)
    return members


def test_every_backend_export_is_reachable_from_the_panel():
    be = _be_export_ids()
    fe = set(_fe_export_ids())
    members = _composite_member_ids()

    # ⛔ Anchor both sides: an empty parse would make this vacuously green, which
    # is the "no tests ran, so nothing is red" failure in another costume.
    assert len(be) > 20, f"only {len(be)} backend export entries parsed"
    assert len(fe) > 20, f"only {len(fe)} frontend export entries parsed"

    unreachable = sorted(be - fe - members)
    assert not unreachable, (
        f"{len(unreachable)} layer(s) exportable by the API but absent from the "
        f"export panel: {unreachable}. The data is served and nobody can reach it."
    )


def test_the_panel_never_offers_an_export_the_api_does_not_have():
    be = _be_export_ids()
    fe = set(_fe_export_ids())

    assert len(fe) > 20, f"only {len(fe)} frontend export entries parsed"

    phantom = sorted(fe - be)
    assert not phantom, (
        f"{len(phantom)} export button(s) with no backend registry entry: "
        f"{phantom}. Clicking one is a 404 the user cannot distinguish from an "
        "empty area of interest."
    )


def test_every_export_gates_on_a_layer_that_exists():
    """The panel shows an entry only while its map layer is active
    (`l.alwaysAvailable || activeLayers.has(mapIdOf(l))`). A `mapLayerId` that
    is not a real layer id can therefore never be true, so the entry silently
    never appears — no error, just an export nobody is ever offered."""
    fe = _fe_export_ids()
    known = set(_py_defaults())

    assert len(known) > 40, f"only {len(known)} layers in LAYER_DEFAULTS_PY"

    dangling = sorted(
        {mapped for mapped in fe.values() if mapped not in known}
    )
    assert not dangling, (
        f"export entries gate on {len(dangling)} id(s) that are not layers: "
        f"{dangling}"
    )
