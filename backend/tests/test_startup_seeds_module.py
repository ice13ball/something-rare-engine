# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""startup_seeds must be importable without importing the application.

schema_steps.py and scripts/migrate.py both import these two functions. If the
import pulls in main.py, migrate.py boots the app it exists to run before, and
the circular path through land_layers makes the import fail outright.
"""
import subprocess
import sys
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def test_startup_seeds_imports_without_the_application():
    # A subprocess, not an import here: pytest's own session may already have
    # main.py in sys.modules, which would hide exactly the coupling under test.
    code = (
        "import sys; import startup_seeds; "
        "assert 'main' not in sys.modules, sorted(m for m in sys.modules if m=='main'); "
        "assert callable(startup_seeds.ensure_layer_config_seed); "
        "assert callable(startup_seeds.ensure_startup_profiles_seed); "
        "print('ok')"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "ok" in r.stdout


def test_main_no_longer_defines_the_seed_functions():
    """The point of the move is that there is ONE definition. Two would drift."""
    src = (BACKEND / "main.py").read_text()
    assert "async def ensure_layer_config_seed" not in src
    assert "async def ensure_startup_profiles_seed" not in src
