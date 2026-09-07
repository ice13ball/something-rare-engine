# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""An id too large for an int4 column is a 404, not a 500.

`seamounts.peak_id` and `hydrothermal_vents.id` are Postgres `integer` (int4).
FastAPI's `int` path type validates "is this an integer" and nothing more, so
`/v1/seo/seamount/2147483648` passed validation, reached asyncpg, and raised a
range error nothing caught — **HTTP 500**.

⚠️ Why that mattered more than a stray 500 usually does: the frontend maps 5xx
to `503 + Retry-After`, correctly, because a 5xx means "ask again later". So an
id that can never exist told Google to keep retrying forever, and made a typo
indistinguishable from a genuine outage — the exact collapse the 2026-08-18
entity-status work exists to prevent, reappearing one layer down.

Measured live 2026-08-19, and the boundary was exact:

    /v1/seo/seamount/2147483647  → 404
    /v1/seo/seamount/2147483648  → 500

These tests are pure — they call the guard directly, with no database — so they
run anywhere and fail for one reason only.
"""

import pytest
from fastapi import HTTPException

from backend.domains.seo import _INT4_MAX, _int4_or_404


def test_int4_max_is_the_postgres_boundary():
    # Not a magic number: it is what an int4 column can hold. If this ever
    # changes, the column type changed and the guard is measuring the wrong
    # thing.
    assert _INT4_MAX == 2**31 - 1


@pytest.mark.parametrize("value", [0, 1, 28715, 37889, _INT4_MAX, -_INT4_MAX - 1])
def test_in_range_ids_pass_through_unchanged(value):
    # The working case, which is what stops "reject everything" from passing.
    assert _int4_or_404(value, "Seamount") == value


@pytest.mark.parametrize("value", [_INT4_MAX + 1, 2_147_483_648, 999_999_999_999, -(2**31) - 1])
def test_out_of_range_ids_raise_404_not_500(value):
    with pytest.raises(HTTPException) as exc:
        _int4_or_404(value, "Seamount")
    # 404, emphatically not 5xx: the id is impossible, so no retry can help.
    assert exc.value.status_code == 404


def test_the_detail_names_the_entity_and_the_id():
    with pytest.raises(HTTPException) as exc:
        _int4_or_404(999_999_999_999, "Vent")
    assert "Vent" in exc.value.detail
    assert "999999999999" in exc.value.detail


def test_every_int_id_seo_endpoint_calls_the_guard():
    """The guard is worthless on an endpoint that forgets it.

    Three endpoints take an int path param; a fourth added later would reach
    asyncpg unguarded and reintroduce the 500. This walks the source rather
    than trusting that whoever adds it will remember.
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "domains" / "seo.py"
    tree = ast.parse(src.read_text())

    unguarded = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        int_args = [
            a.arg for a in node.args.args
            if isinstance(a.annotation, ast.Name) and a.annotation.id == "int"
        ]
        # Only route handlers — a plain helper taking an int is not a URL.
        is_route = any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and isinstance(d.func.value, ast.Name)
            and d.func.value.id == "router"
            for d in node.decorator_list
        )
        if not (int_args and is_route):
            continue
        calls = {
            n.func.id for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        if "_int4_or_404" not in calls:
            unguarded.append(node.name)

    assert not unguarded, (
        f"router endpoints take an int id without calling _int4_or_404: {unguarded}. "
        "An out-of-int4 id will reach asyncpg and become a 500, which the frontend "
        "turns into a 503 — telling Google to retry an id that can never exist."
    )
