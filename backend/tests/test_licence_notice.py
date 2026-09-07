# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Guard for the AGPL-3.0-or-later §7(b) attribution requirement
(see LICENSE-ADDITIONAL-TERMS.md and NOTICE at the repo root).

Two independent things must stay true, and each has broken silently before
for an adjacent guard scoped too narrowly (see test_sample_date_contract.py):

1. The running app's shipping frontend content must mention AGPL and link
   the public source mirror, reachable from the UI as the "Appropriate Legal
   Notices" the licence requires. This scans the SAME surface the soil-carbon
   guard uses (`_iter_frontend_shipping_files`) rather than a second,
   differently-scoped scanner — that helper exists precisely because a guard
   scoped to one directory has already missed things three times in this repo.

2. Every Python file under backend/ carries the SPDX header. This reuses the
   exact file selection `scripts/add-spdx-headers.py` uses (not a
   reimplementation of its exclusion rules), so the guard and the script that
   maintains compliance can never drift apart on which files count.
"""

import importlib.util
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_sample_date_contract import _iter_frontend_shipping_files  # noqa: E402


def _load_spdx_script():
    """Import scripts/add-spdx-headers.py as a module without needing
    `scripts/` to be a package (it deliberately is not — see export-public.sh,
    which classifies the whole `scripts/` prefix as NEVER-public)."""
    script_path = REPO_ROOT / "scripts" / "add-spdx-headers.py"
    spec = importlib.util.spec_from_file_location("add_spdx_headers", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_SPDX = _load_spdx_script()


def test_shipping_frontend_mentions_agpl_and_links_the_source_repo():
    """AGPL §7(b) requires a notice reachable from the running program's UI:
    the licence name and a link to the source. If neither string appears
    anywhere in the shipping frontend, there is no Appropriate Legal Notice —
    only source code that happens to carry a licence file no user ever sees."""
    has_agpl = False
    has_source_link = False
    for path in _iter_frontend_shipping_files():
        text = path.read_text(encoding="utf-8")
        if "AGPL" in text:
            has_agpl = True
        if "github.com/ice13ball/something-rare-engine" in text:
            has_source_link = True
        if has_agpl and has_source_link:
            break
    assert has_agpl, "no shipping frontend file mentions AGPL — the licence notice is not reachable from the UI"
    assert has_source_link, (
        "no shipping frontend file links the public source mirror "
        "(https://github.com/ice13ball/something-rare-engine) — the §7(b) source link is not reachable from the UI"
    )


def test_every_backend_python_file_carries_the_spdx_header():
    """Same file selection as scripts/add-spdx-headers.py — this guard and
    the script that stamps the header must agree on which files count, or a
    future exclusion added to one and not the other silently rots the pair."""
    backend_root = (REPO_ROOT / "backend").resolve()
    offenders = []
    for path in _SPDX.iter_candidate_files():
        if path.suffix != ".py":
            continue
        try:
            path.resolve().relative_to(backend_root)
        except ValueError:
            continue  # not under backend/ (e.g. scripts/*.py) — out of scope for this guard
        text = path.read_text(encoding="utf-8")
        if not _SPDX.already_stamped(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], (
        f"{len(offenders)} backend .py file(s) are missing the SPDX header "
        f"(run `python3 scripts/add-spdx-headers.py` to fix): {sorted(offenders)}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
