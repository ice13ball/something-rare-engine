# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Shared AST-based scanner for environment variable names read by the backend.

Walks every .py file under backend/ EXCLUDING backend/tests/ itself, and collects
every string literal passed as the variable-name argument to:
  - os.getenv("NAME", ...)
  - os.environ.get("NAME", ...)
  - os.environ["NAME"]

Also collects a list of call sites where the variable name argument is NOT a
string literal (f-string, variable, comprehension, etc.) so callers can report
them separately -- those cannot be enumerated by this scanner.

backend/scripts/ and backend/schema/ ARE included: they run as part of the
deployed backend (one-off/maintenance scripts and DDL/migration helpers that
read the same .env), not test fixtures, so their env var names belong in
.env.example just like everything else. Only backend/tests/ is excluded,
because test fixtures may reference names that are not real runtime config.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _iter_backend_py_files():
    for dirpath, dirnames, filenames in os.walk(BACKEND_ROOT):
        rel = Path(dirpath).relative_to(BACKEND_ROOT)
        # Exclude backend/tests/ (this directory) and common non-source dirs.
        parts = rel.parts
        if parts and parts[0] in ("tests", "__pycache__", ".venv", "venv", "node_modules"):
            dirnames[:] = []
            continue
        # also prune nested __pycache__/venv dirs
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".venv", "venv", "node_modules")]
        for fn in filenames:
            if fn.endswith(".py"):
                yield Path(dirpath) / fn


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def scan() -> tuple[set[str], list[tuple[str, int, str]]]:
    """Returns (literal_names, non_literal_sites).

    non_literal_sites is a list of (file, lineno, snippet-ish description).
    """
    names: set[str] = set()
    non_literal: list[tuple[str, int, str]] = []

    for path in _iter_backend_py_files():
        try:
            src = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError:
            continue

        rel_path = str(path.relative_to(BACKEND_ROOT.parent))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func

            # os.getenv(...) / os.environ.get(...)
            is_getenv = (
                isinstance(func, ast.Attribute)
                and func.attr == "getenv"
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            )
            is_environ_get = (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "environ"
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "os"
            )
            if (is_getenv or is_environ_get) and node.args:
                name = _const_str(node.args[0])
                if name is not None:
                    names.add(name)
                else:
                    non_literal.append((rel_path, node.lineno, ast.dump(node.args[0])[:80]))

        # os.environ["NAME"] / os.environ.get(...) handled above; subscript form:
        for node in ast.walk(tree):
            if isinstance(node, ast.Subscript):
                value = node.value
                if (
                    isinstance(value, ast.Attribute)
                    and value.attr == "environ"
                    and isinstance(value.value, ast.Name)
                    and value.value.id == "os"
                ):
                    slice_node = node.slice
                    name = _const_str(slice_node)
                    if name is not None:
                        names.add(name)
                    else:
                        non_literal.append((rel_path, node.lineno, ast.dump(slice_node)[:80]))

    return names, non_literal


if __name__ == "__main__":
    found, non_lit = scan()
    print(f"Discovered {len(found)} distinct env var names:")
    for n in sorted(found):
        print(f"  {n}")
    if non_lit:
        print(f"\n{len(non_lit)} non-literal getenv/environ call sites (cannot be enumerated):")
        for f, ln, snip in non_lit:
            print(f"  {f}:{ln}  {snip}")
