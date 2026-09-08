# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""There is exactly one ordered list of schema steps.

Order is semantics: an index or ALTER ahead of its CREATE TABLE fails at boot.
schema/__init__.py says the ordering is load-bearing and
tests/test_ensure_schema_ddl.py snapshots it. A second list is a second truth.
"""
import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _is_ensure_name(node: ast.AST) -> bool:
    """True for a bare (`ensure_foo`) or qualified (`schema.ensure_foo`) reference
    to an `ensure_*` name — a regex only ever caught the bare form."""
    if isinstance(node, ast.Name):
        return node.id.startswith("ensure_")
    if isinstance(node, ast.Attribute):
        return node.attr.startswith("ensure_")
    return False


def _is_ensure_pair(node: ast.AST) -> bool:
    """True if `node` is a 2-tuple shaped like `(ensure_foo, "ensure_foo")`."""
    if not (isinstance(node, ast.Tuple) and len(node.elts) == 2):
        return False
    fn, name = node.elts
    return (
        _is_ensure_name(fn)
        and isinstance(name, ast.Constant)
        and isinstance(name.value, str)
        and name.value.startswith("ensure_")
    )


def find_inline_ensure_pairs(source: str) -> list[int]:
    """Line numbers of every `(ensure_x, "ensure_x")`-shaped tuple in `source`.

    AST-based, not text-based, so it survives what defeated the regex this
    replaces: a tuple reflowed across lines with a trailing comma before the
    closing paren (a routine Black-style reformat), and a qualified reference
    (`schema.ensure_foo`) instead of a bare name. Neither changes the parse
    tree shape, so both are still caught.

    The ONE legitimate occurrence is exempt: every descendant of the value of
    a module-level assignment to the name `SCHEMA_STEPS` — schema_steps.py's
    own canonical list — is excluded from the walk. Any OTHER occurrence,
    anywhere, under any other name (a caller's local `steps = [...]`, a bare
    for-loop iterable, or anything else), is exactly the second copy this
    guard exists to catch.
    """
    tree = ast.parse(source)

    exempt_ids: set[int] = set()
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        if (isinstance(target, ast.Name) and target.id == "SCHEMA_STEPS"
                and getattr(node, "value", None) is not None):
            exempt_ids.update(id(n) for n in ast.walk(node.value))

    hits = []
    for node in ast.walk(tree):
        if id(node) in exempt_ids:
            continue
        if _is_ensure_pair(node):
            hits.append(node.lineno)
    return hits


def test_there_are_sixteen_steps_in_order():
    from schema_steps import SCHEMA_STEPS
    names = [name for _fn, name in SCHEMA_STEPS]
    assert names == [
        "ensure_schema",
        "ensure_api_access_schema",
        "ensure_log_schema",
        "ensure_admin_schema",
        "ensure_layer_config_seed",
        "ensure_layer_temporal_coverage",
        "ensure_startup_profiles_seed",
        "ensure_land_schema",
        "ensure_overlap_views",
        "ensure_vessel_events_schema",
        "ensure_sar_schema",
        "ensure_ais_schema",
        "ensure_density_hex_cells",
        "ensure_density_source_indexes",
        "ensure_monitoring_density_matview",
        "ensure_species_cache_table",
    ]


def test_every_step_is_callable():
    from schema_steps import SCHEMA_STEPS
    for fn, name in SCHEMA_STEPS:
        assert callable(fn), f"{name} is not callable"


def test_no_caller_keeps_its_own_list():
    """The shape of the code IS the property here, so reading source is correct.

    A second occurrence of the (ensure_x, "ensure_x") shape anywhere in either
    caller means the single source of truth has been forked again.
    """
    for rel in ("main.py", "scripts/ci_bootstrap_db.py", "scripts/migrate.py"):
        src = (BACKEND / rel).read_text()
        hits = find_inline_ensure_pairs(src)
        assert not hits, f"{rel} still defines its own step pairs at line(s): {hits}"


def test_ast_checker_catches_reflowed_multiline_tuple():
    """A Black-style reflow with a trailing comma before the closing paren.

    Verified false negative on the old regex `\\(\\s*ensure_\\w+\\s*,\\s*["']ensure_\\w+["']\\s*\\)`:
    `findall` on this exact shape returns []. The AST walk does not care about
    line breaks or trailing commas.
    """
    src = (
        "STEPS = [\n"
        "    (\n"
        "        ensure_foo,\n"
        "        \"ensure_foo\",\n"
        "    ),\n"
        "]\n"
    )
    hits = find_inline_ensure_pairs(src)
    assert hits, "AST checker missed a reflowed multi-line ensure-pair tuple"


def test_ast_checker_catches_qualified_reference():
    """`(schema.ensure_foo, "ensure_foo")` — the old regex only matched a bare name."""
    src = 'STEPS = [(schema.ensure_foo, "ensure_foo")]\n'
    hits = find_inline_ensure_pairs(src)
    assert hits, "AST checker missed a qualified (module.ensure_x, ...) reference"


def test_ast_checker_does_not_fire_on_the_import():
    """The legitimate way for a caller to get the list: import and iterate it."""
    src = (
        "from schema_steps import SCHEMA_STEPS\n\n"
        "for step, name in SCHEMA_STEPS:\n"
        "    pass\n"
    )
    hits = find_inline_ensure_pairs(src)
    assert hits == [], f"false positive on a bare import + iterate: {hits}"


def test_ast_checker_does_not_fire_on_schema_steps_py_itself():
    """schema_steps.py legitimately contains the one real list, under the name
    SCHEMA_STEPS — that is not a second copy, it is the first and only one."""
    src = (BACKEND / "schema_steps.py").read_text()
    hits = find_inline_ensure_pairs(src)
    assert hits == [], (
        f"AST checker flagged schema_steps.py's own canonical SCHEMA_STEPS "
        f"list as if it were a second copy: {hits}"
    )


def test_schema_steps_imports_without_the_application():
    import subprocess, sys
    code = "import sys; import schema_steps; assert 'main' not in sys.modules; print('ok')"
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
