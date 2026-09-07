# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The refactor gate imports `main` on a machine with no DB and no heavy
optional deps. Lock that in so a future eager import cannot silently break it."""
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def test_main_imports_without_db_or_heavy_deps():
    # Run in a subprocess so a successful import cannot pollute this process,
    # and so we control the environment precisely.
    code = (
        "import sys, os; sys.path.insert(0, '.');\n"
        "os.environ.pop('DATABASE_URL', None);\n"
        "import main;\n"
        "assert len(main.app.routes) > 200, len(main.app.routes);\n"
        "print('OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"`import main` failed.\nstdout: {proc.stdout}\nstderr: {proc.stderr[-3000:]}"
    )
    assert "OK" in proc.stdout


def test_ocean_currents_does_not_import_copernicusmarine_eagerly():
    src = (BACKEND / "services" / "ocean_currents.py").read_text()
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import copernicusmarine", "from copernicusmarine")):
            # A lazy import lives inside a function and is therefore indented.
            assert line != stripped, (
                "copernicusmarine must be imported lazily (inside a function), "
                f"found top-level: {line!r}"
            )
