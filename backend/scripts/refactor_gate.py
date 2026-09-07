#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Refactor gate — proves a code move did not change the API surface.

Usage, run from the repo root:

    python3 backend/scripts/refactor_gate.py snapshot   # before you move code
    python3 backend/scripts/refactor_gate.py check      # after you move code

`check` exits non-zero and prints every difference if the surface changed.

What this proves: no endpoint vanished, was renamed, changed method, changed
parameters or changed response model; no sync source fell out of a registry;
no entry was accidentally double-registered or dropped to a stale duplicate
(counts are compared, not just set membership).

What this does NOT prove: that the logic inside a handler still works. This
gate is not a substitute for tests. See the spec's "Honest limit of this gate".
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
SNAPSHOT = BACKEND.parent / ".refactor-gate" / "surface.json"

_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH")


def collect_surface(main_module) -> dict:
    """Read the live app's surface. `main_module` is an imported `main`."""
    import api_docs

    routes = []
    for r in main_module.app.routes:
        path = getattr(r, "path", None)
        if path is None:
            continue
        methods = sorted(m for m in getattr(r, "methods", set()) or set() if m in _METHODS)
        for m in methods or ["-"]:
            routes.append(f"{m} {path}")

    return {
        "routes": sorted(routes),
        "openapi": api_docs.build_openapi(main_module.app),
        "sync_sources": sorted(getattr(main_module, "_SYNC_SOURCES", {})),
        "source_to_action": sorted(getattr(main_module, "_SOURCE_TO_ACTION", {})),
    }


def diff_surface(before: dict, after: dict) -> list[str]:
    """Return human-readable differences. Empty list == surfaces identical.

    Route order is deliberately ignored: moving endpoints into an APIRouter
    changes registration order, which is not part of the contract. Counts are
    NOT ignored: a `Counter` comparison catches an entry that got accidentally
    double-registered (e.g. copied into a router but left in place in
    `main.py`) or dropped to a stale duplicate — the most probable mistake
    when moving endpoints, and one plain set arithmetic cannot see.
    """
    diffs: list[str] = []

    for key in ("routes", "sync_sources", "source_to_action"):
        before_c = Counter(before.get(key, []))
        after_c = Counter(after.get(key, []))
        gone = sorted(k for k in before_c if k not in after_c)
        added = sorted(k for k in after_c if k not in before_c)
        changed = sorted(k for k in before_c if k in after_c and before_c[k] != after_c[k])
        for g in gone:
            diffs.append(f"{key}: REMOVED  {g}")
        for a in added:
            diffs.append(f"{key}: ADDED    {a}")
        for c in changed:
            diffs.append(f"{key}: COUNT {before_c[c]} -> {after_c[c]}  {c}")

    b_api = json.dumps(before.get("openapi", {}), sort_keys=True, indent=1).splitlines()
    a_api = json.dumps(after.get("openapi", {}), sort_keys=True, indent=1).splitlines()
    if b_api != a_api:
        import difflib

        delta = [
            ln
            for ln in difflib.unified_diff(b_api, a_api, "before", "after", lineterm="", n=1)
            if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))
        ]
        diffs.append(f"openapi: {len(delta)} changed line(s); first 40 shown")
        diffs.extend(f"  {ln}" for ln in delta[:40])

    return diffs


def _load_main():
    sys.path.insert(0, str(BACKEND))
    import main  # noqa: E402

    return main


def main_cli() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("snapshot", "check"):
        print(__doc__)
        return 2
    mode = sys.argv[1]
    surface = collect_surface(_load_main())

    if mode == "snapshot":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(surface, sort_keys=True, indent=1))
        print(
            f"snapshot written: {SNAPSHOT}\n"
            f"  routes           {len(surface['routes'])}\n"
            f"  openapi paths    {len(surface['openapi'].get('paths', {}))}\n"
            f"  sync sources     {len(surface['sync_sources'])}\n"
            f"  source→action    {len(surface['source_to_action'])}"
        )
        return 0

    if not SNAPSHOT.exists():
        print(f"no snapshot at {SNAPSHOT} — run `snapshot` first", file=sys.stderr)
        return 2
    diffs = diff_surface(json.loads(SNAPSHOT.read_text()), surface)
    if diffs:
        print(f"GATE FAILED — {len(diffs)} difference(s):", file=sys.stderr)
        for d in diffs:
            print(f"  {d}", file=sys.stderr)
        return 1
    print(
        f"GATE PASSED — surface unchanged "
        f"({len(surface['routes'])} routes, "
        f"{len(surface['openapi'].get('paths', {}))} openapi paths, "
        f"{len(surface['sync_sources'])} sync sources)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
