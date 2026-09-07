# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Every `main.<attr>` (and `land_layers.<attr>`) access outside its own file must resolve.

Phase 3 moved six cache globals into domain modules while
`routers/admin_layers_api.py` still reached for them through `main.`.
Nothing caught it: the refactor gate compares route membership (the route
was unchanged), the admin router is excluded from the public OpenAPI, and
the Phase-2 unresolved-name sweep only inspects LOAD_GLOBAL, not attribute
access on an imported module. The result was a 500 on a live endpoint.

`land_layers` carries the identical hazard: `domains/biodiversity.py` does
`import land_layers as _ll; _ll._deepdata_stations_cache = None` — a
cross-module *write* (ast.Attribute with Store ctx) to a private global.
`_attr_refs_for` matches `ast.Attribute` regardless of `ctx`, so it covers
stores as well as reads for either module.
"""
import ast
import importlib
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _attr_refs_for(module_name: str, own_file: str):
    """(file, line, attr) for every `<module_name>.<attr>` outside `own_file`.

    Matches `ast.Attribute` regardless of `ctx` (Load/Store/Del all walk the
    same node shape), so an assignment like `_ll._cache = None` is covered
    exactly like a read.
    """
    refs = []
    for path in sorted(BACKEND.rglob("*.py")):
        if "tests" in path.parts or path.name == own_file:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        aliases = {module_name}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == module_name:
                        aliases.add(a.asname or module_name)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
            ):
                refs.append((path.relative_to(BACKEND), node.lineno, node.attr))
    return refs


def _main_attr_refs():
    return _attr_refs_for("main", "main.py")


def test_every_main_attr_ref_resolves():
    sys.path.insert(0, str(BACKEND))
    main = importlib.import_module("main")
    refs = _main_attr_refs()
    assert refs, "sweep found no main.<attr> accesses — it has stopped working"
    missing = [(f, l, a) for f, l, a in refs if not hasattr(main, a)]
    assert not missing, "main.<attr> accesses that no longer resolve: " + ", ".join(
        f"{f}:{l} main.{a}" for f, l, a in missing
    )


def test_every_land_layers_attr_ref_resolves():
    """The cross-module write this sweep was built to catch —
    `domains/biodiversity.py` doing `import land_layers as _ll;
    _ll._deepdata_stations_cache = None` — was removed 2026-08-21 in favour of
    a named function (`domains.land.density.clear_deepdata_stations_cache`).
    No other file reaches for `land_layers.<attr>` any more (main.py imports
    the re-exported names directly via `from land_layers import ...`, which
    is an ImportFrom, not an Attribute node this sweep matches).

    So the sweep now legitimately finds zero refs, and the old "sweep found
    nothing — it broke" guard would trip permanently for a correct reason.
    Rather than delete the guard, its assertion is flipped: assert the count
    is exactly zero, with the resolve-check kept (a no-op today, but it means
    the moment anyone reintroduces a `land_layers.<attr>` access — the exact
    pattern that caused the live 500 this file exists to prevent — the count
    changes to nonzero and this test starts checking it again, same as
    before. Kept pointed at land_layers rather than domains.land because no
    file references `domains.land.<attr>` as an attribute either (all
    consumers use `from domains.land.x import y`); there is nothing to sweep
    on either name today.
    """
    sys.path.insert(0, str(BACKEND))
    land_layers = importlib.import_module("land_layers")
    refs = _attr_refs_for("land_layers", "land_layers.py")
    assert refs == [], (
        "sweep found land_layers.<attr> accesses again — verify each one is "
        "safe, then update this test's expectation deliberately: "
        + ", ".join(f"{f}:{l} land_layers.{a}" for f, l, a in refs)
    )
    missing = [(f, l, a) for f, l, a in refs if not hasattr(land_layers, a)]
    assert not missing, "land_layers.<attr> accesses that no longer resolve: " + ", ".join(
        f"{f}:{l} land_layers.{a}" for f, l, a in missing
    )
