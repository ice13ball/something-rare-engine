# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""ABYSSAL_STANDBY guard: lifespan() must spawn zero background tasks under it.

Scoped to the `lifespan` function node only — main.py has 43 asyncio.create_task
calls total, and at least one (`_run_tracked`, in the admin force-sync handler)
is a request handler, not a startup task. A module-wide walk would wrongly
demand that call move under the standby flag too.
"""
import ast
import pathlib

MAIN = pathlib.Path(__file__).resolve().parent.parent / "main.py"


def _lifespan_node():
    tree = ast.parse(MAIN.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan":
            return node
    raise AssertionError("lifespan() not found in main.py")


def _is_standby_test(test: ast.expr) -> bool:
    return "ABYSSAL_STANDBY" in ast.dump(test)


def _create_task_calls(lifespan_node):
    """Walk lifespan(), tracking whether we're inside an `if` guarded by
    ABYSSAL_STANDBY. Returns (guarded_lines, unguarded_lines) for every
    `asyncio.create_task(...)` call found."""
    guarded = []
    unguarded = []

    def walk(node, inside_standby_guard):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If):
                # The `else:` branch of `if ABYSSAL_STANDBY: ... else: <tasks>`
                # is where the guarded tasks live — it is NOT itself the
                # ABYSSAL_STANDBY branch, but it is reached only when the
                # standby flag is checked. Treat both `body` and `orelse` of
                # any if/else that tests ABYSSAL_STANDBY as guarded, since
                # spawning is conditioned on that flag either way.
                is_standby_if = _is_standby_test(child.test)
                walk_body = inside_standby_guard or is_standby_if
                for stmt in child.body:
                    walk(stmt, walk_body)
                for stmt in child.orelse:
                    walk(stmt, walk_body)
                continue
            if isinstance(child, ast.Call):
                func = child.func
                is_create_task = (
                    isinstance(func, ast.Attribute)
                    and func.attr == "create_task"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "asyncio"
                )
                if is_create_task:
                    (guarded if inside_standby_guard else unguarded).append(child.lineno)
            walk(child, inside_standby_guard)

    walk(lifespan_node, False)
    return guarded, unguarded


def test_standby_flag_guards_every_background_task_spawn():
    lifespan_node = _lifespan_node()
    guarded, unguarded = _create_task_calls(lifespan_node)

    assert guarded, (
        "Expected asyncio.create_task(...) calls guarded by an "
        "`if ... ABYSSAL_STANDBY ...` branch in lifespan() — found none. "
        "Either the guard moved or this test is now vacuous."
    )
    assert not unguarded, (
        "asyncio.create_task(...) call(s) in lifespan() are NOT guarded by "
        "ABYSSAL_STANDBY — a warm standby would spawn these. "
        f"Unguarded line(s) in backend/main.py: {unguarded}"
    )
