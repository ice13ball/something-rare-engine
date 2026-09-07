# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Every on-disk cache root must come from an environment variable.

Two separate reasons, and the second is the one that bites:

1. A hard-coded /var/cache path is not writable by a developer without root, so
   a newcomer running the project cannot exercise the code that uses it.

2. The reader and the writer of the SAME cache must resolve to the SAME root.
   routers/spatial_v2.py read RASTER_TILE_CACHE_DIR while offshore_tile_baker.py
   hard-coded that variable's default. Setting it moved the reader and left the
   writer behind, so every baked tile was written where nothing would look for
   it — the pre-baked pyramid silently stopped hitting and every request fell
   through to on-demand rendering, with no error anywhere.
"""
import ast
import os
import pathlib
import subprocess
import sys

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _py_sources():
    for p in BACKEND.rglob("*.py"):
        if any(part in {"tests", "__pycache__", "node_modules"} for part in p.parts):
            continue
        yield p


def _docstring_constants(tree):
    """Every string node that is a module/class/function docstring.

    A docstring naming /var/cache is documentation, not a hard-coded root — four
    modules describe their cache layout in prose, and a guard that cannot tell
    prose from code reports them forever until someone deletes the guard.
    """
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def test_no_cache_root_is_hard_coded():
    offenders = []
    for path in _py_sources():
        src = path.read_text(encoding="utf-8")
        if "/var/cache" not in src:
            continue
        tree = ast.parse(src)
        docstrings = _docstring_constants(tree)
        lines = src.splitlines()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if "/var/cache" not in node.value or id(node) in docstrings:
                continue
            line = lines[node.lineno - 1]
            if "getenv" in line or "environ" in line:
                continue
            offenders.append(f"{path.relative_to(BACKEND)}:{node.lineno}")
    assert offenders == [], (
        "these cache roots cannot be redirected with an environment variable, so a "
        f"developer without root cannot use them: {offenders}"
    )


def test_baker_and_reader_share_one_raster_root(tmp_path):
    """Redirect RASTER_TILE_CACHE_DIR and require BOTH modules to follow.

    Runs in a SUBPROCESS deliberately. The first version used
    importlib.reload() in-process, which left routers.spatial_v2 permanently
    reloaded against a temporary directory that pytest then deleted — seven
    unrelated tests in test_raster_cache_path_safety.py failed afterwards.
    A subprocess cannot leak module state back into this session.
    """
    root = tmp_path / "raster"
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "import routers.spatial_v2 as sv2, offshore_tile_baker as baker\n"
        "print(sv2._BAKED_DIR); print(baker._BAKED_DIR)"
    ) % str(BACKEND)
    env = {**os.environ, "RASTER_TILE_CACHE_DIR": str(root)}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    reader, writer = out.stdout.strip().splitlines()

    assert reader.startswith(str(root)), f"the tile route ignored the variable: {reader}"
    assert writer.startswith(str(root)), f"the baker ignored the variable: {writer}"
    assert reader == writer, (
        f"the baker writes to {writer} but the tile route reads {reader} — baked "
        "tiles would never be found and every request would re-render, silently"
    )


def test_no_module_has_an_orphaned_docstring():
    """A string sitting at top level while the module has no docstring.

    Adding an import ABOVE a module docstring demotes it from `__doc__` to a
    no-op expression. Nothing errors, nothing warns, `help()` just goes blank —
    it happened here while making cache roots configurable, in exactly one file
    out of four, and only a syntax-aware check noticed.
    """
    offenders = []
    for path in _py_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if ast.get_docstring(tree) is not None:
            continue
        for node in tree.body:
            if (isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                    and len(node.value.value) > 40):
                offenders.append(f"{path.relative_to(BACKEND)}:{node.lineno}")
                break
    assert offenders == [], (
        "these modules have a docstring-shaped string that is not the module "
        f"docstring — something was inserted above it: {offenders}"
    )
