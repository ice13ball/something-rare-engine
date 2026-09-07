# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

from layer_ops import LAYER_OPS, resolve_ops, has_table, age_bucket


def test_baked_layer_has_no_table():
    ops = resolve_ops("marine-carbon")
    assert ops is not None
    assert ops["tables"] is None
    assert has_table("marine-carbon") is False


def test_vector_layer_has_tables():
    ops = resolve_ops("methane-seeps")
    assert ops["tables"] == ("seaflea_seeps",)
    assert has_table("methane-seeps") is True


def test_multi_table_layer_lists_all():
    assert resolve_ops("memento")["tables"] == ("memento_casts", "memento_samples")


def test_unknown_layer_returns_none():
    assert resolve_ops("does-not-exist") is None
    assert has_table("does-not-exist") is False


def test_worker_baked_layers_with_tables_are_purgeable():
    # vme-suitability / coral-acid-exposure are baked out-of-process but DO have real
    # tables, so they must expose a row-count + be purgeable (force-sync re-bakes them).
    assert resolve_ops("vme-suitability")["tables"] == ("vme_cells",)
    assert has_table("vme-suitability") is True
    assert resolve_ops("coral-acid-exposure")["tables"] == ("vme_exposure_cells",)
    assert has_table("coral-acid-exposure") is True


def test_age_bucket_stale_and_fresh():
    assert age_bucket(None) == {"age_seconds": None, "stale": False}
    assert age_bucket(100.0)["stale"] is False
    assert age_bucket(8 * 86400)["stale"] is True


def test_every_layer_config_id_should_have_ops():
    # Guard: LAYER_OPS must cover every id the DB seed knows.
    # (Enumerated ids are asserted against LAYER_DEFAULTS_PY in Step 4's live check;
    #  here we assert the registry is non-trivial and well-formed.)
    assert len(LAYER_OPS) >= 40
    for lid, ops in LAYER_OPS.items():
        assert set(ops) == {"sync_source", "log_source", "tables", "count_sql"}
        if ops["tables"] is not None:
            assert isinstance(ops["tables"], tuple) and ops["count_sql"]
        else:
            assert ops["count_sql"] is None
