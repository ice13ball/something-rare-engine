# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Unit tests for the atomic, owner-only .env writer used by admin token
rotation (backend/routers/admin_layers_api.py::_rewrite_env_var).

Passes an explicit env_path so the heavy `import main` chain is never
triggered (see the `if env_path is None` guard in the function itself).
"""
from __future__ import annotations

import os
import stat

from routers.admin_layers_api import _rewrite_env_var


def test_updates_target_key_and_preserves_others(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DATABASE_URL=postgres://x\n"
        "ADMIN_DASHBOARD_TOKEN=old-token\n"
        "FIRMS_MAP_KEY=abc123\n"
    )

    _rewrite_env_var("ADMIN_DASHBOARD_TOKEN", "new-token", env_path=env_file)

    lines = env_file.read_text().splitlines()
    assert "ADMIN_DASHBOARD_TOKEN=new-token" in lines
    assert "DATABASE_URL=postgres://x" in lines
    assert "FIRMS_MAP_KEY=abc123" in lines
    assert "ADMIN_DASHBOARD_TOKEN=old-token" not in lines


def test_appends_missing_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=postgres://x\n")

    _rewrite_env_var("ADMIN_DASHBOARD_TOKEN", "brand-new", env_path=env_file)

    lines = env_file.read_text().splitlines()
    assert "DATABASE_URL=postgres://x" in lines
    assert "ADMIN_DASHBOARD_TOKEN=brand-new" in lines


def test_result_file_mode_is_0600_even_if_preexisting_was_0644(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ADMIN_DASHBOARD_TOKEN=old\n")
    os.chmod(env_file, 0o644)

    _rewrite_env_var("ADMIN_DASHBOARD_TOKEN", "new", env_path=env_file)

    mode = stat.S_IMODE(os.stat(env_file).st_mode)
    assert mode == 0o600


def test_no_tmp_file_left_behind(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("ADMIN_DASHBOARD_TOKEN=old\n")

    _rewrite_env_var("ADMIN_DASHBOARD_TOKEN", "new", env_path=env_file)

    assert not (tmp_path / ".env.tmp").exists()
