# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A sync that bails out for want of a credential must leave a row behind.

CLAUDE.md's engine rules already say it: "Every early return in a sync function
needs `_log_sync`, not just the interesting one." On 2026-09-12 five of the six
`if not token:` guards in `domains/onc.py` still returned in silence, and the
sixth logged in the one shape that is worse than silence
(`_log_sync(src, 0, 0)` stamps `last_synced_at = NOW()`, so an unconfigured
layer reads as freshly synced forever).

This is a rule about the SHAPE of the code, so reading the source is the correct
way to check it — there is no runtime path that visits all six guards. It is
AST-based rather than textual so that reformatting, an added log line, or a
renamed message cannot make it quietly stop matching.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent

#: Modules whose credential guards must record. Add a module here when it grows
#: a sync that can bail out for want of a key.
GUARDED_MODULES = ("domains/onc.py",)

#: The only acceptable recorder for a guard that could not run. `_log_sync` is
#: deliberately NOT in this set: it advances `last_synced_at`, which is a claim
#: the caller is in no position to make.
SKIP_RECORDERS = {"_log_sync_skipped", "log_sync_skipped"}


def _called_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            if isinstance(fn, ast.Name):
                out.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                out.add(fn.attr)
    return out


_ROUTE_DECORATORS = {"get", "post", "put", "patch", "delete"}


def _is_route_handler(fn: ast.AST) -> bool:
    """True for `@router.get(...)`-style handlers.

    ⛔ These are deliberately excluded, and the distinction is the whole point.
    A REQUEST handler with no credential answers its caller — `live_onc` returns
    `{"available": False, "reason": "ONC_TOKEN not configured"}`, which is
    correct and is the only place in the backend that already models the
    "credential missing" state honestly. A SYNC has no caller to answer, so its
    only way of saying anything is the `sync_log` row. Policing endpoints here
    would flag correct code and the rule would get switched off.
    """
    for dec in getattr(fn, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr in _ROUTE_DECORATORS:
            return True
    return False


def _token_guards(tree: ast.AST) -> list[ast.If]:
    """Every `if not token:` block that returns, inside a non-endpoint function."""
    guards = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if _is_route_handler(fn):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if not (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)):
                continue
            operand = test.operand
            if not (isinstance(operand, ast.Name) and operand.id == "token"):
                continue
            if not any(isinstance(s, ast.Return) for s in ast.walk(node)):
                continue
            guards.append(node)
    return guards


@pytest.mark.parametrize("module", GUARDED_MODULES)
def test_every_credential_guard_records_that_it_could_not_run(module: str):
    path = BACKEND / module
    tree = ast.parse(path.read_text(encoding="utf-8"))

    guards = _token_guards(tree)
    # ⛔ An empty list would make every assertion below vacuously true — the
    # exact "no tests ran, so nothing is red" failure. Anchor on a real count.
    assert len(guards) >= 6, (
        f"only {len(guards)} token guards found in {module} — the matcher has "
        "drifted away from the code it is supposed to police, so its silence "
        "means nothing"
    )

    silent = [
        g.lineno for g in guards if not (_called_names(g) & SKIP_RECORDERS)
    ]
    assert not silent, (
        f"{module}: {len(silent)} credential guard(s) return without recording, "
        f"at line(s) {silent}. A sync that never ran and a sync that ran and "
        "could not run must not look the same from outside."
    )


@pytest.mark.parametrize("module", GUARDED_MODULES)
def test_no_credential_guard_claims_a_successful_sync(module: str):
    """`_log_sync(src, 0, 0)` inside a credential guard is the convenient lie:
    it sets `last_synced_at = NOW()`, so the staleness monitor and the
    user-facing "Dates & Freshness" tab both read the layer as current."""
    path = BACKEND / module
    tree = ast.parse(path.read_text(encoding="utf-8"))

    lying = [
        g.lineno
        for g in _token_guards(tree)
        if "_log_sync" in _called_names(g) or "log_sync" in _called_names(g)
    ]
    assert not lying, (
        f"{module}: credential guard(s) at line(s) {lying} call _log_sync, which "
        "stamps last_synced_at = NOW(). Use _log_sync_skipped — it records the "
        "attempt and its reason while letting the source keep ageing."
    )
