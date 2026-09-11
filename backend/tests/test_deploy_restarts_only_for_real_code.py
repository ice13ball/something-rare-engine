# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""A production restart must be caused by code that can change how the API behaves.

`deploy-if-new.sh` polls `dev` every 60 s on the VPS. Its backend branch runs
migrate.py and restarts `abyssal-api`; nginx fails over to the standby on 8769,
but the changeover is not free and a user loading the map during it sees layers
fail.

On 2026-09-11 a commit of three markdown documents and ONE new test file matched
`^backend/` and restarted production at 10:00:27 for nothing.

⛔ This test EXECUTES the predicate out of the real script. It does not grep for
it. A `grep` test would pass against a comment describing the rule, and five
guards in this repo have already gone red on their own prose.

⛔ The dangerous direction is the OTHER one: a real code change that fails to
restart leaves the API serving stale code. Every table row below that expects
RESTART is therefore as load-bearing as the ones that expect no restart.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[2] / "backend" / "ops"
SCRIPT = OPS / "scripts" / "deploy-if-new.sh"

# ⛔ This test SHIPS to the public mirror; its subject does not. `backend/ops/`
# describes the live VPS and is on the export's NEVER list, so in the mirror the
# script is simply absent and there is nothing here to test. Skipping is correct
# there — failing would hand every reader of the public repository a red suite
# for a file they were never meant to have.
#
# ⛔ The condition is the DIRECTORY, not the file. If `backend/ops/` exists but
# the script inside it does not, someone moved or deleted it here, and that must
# go RED rather than quietly skip. Verified by building the real export
# (`scripts/export-public.sh --out …`) on 2026-09-11: the test is present in the
# export tree, the script is not.
pytestmark = pytest.mark.skipif(
    not OPS.is_dir(),
    reason="backend/ops/ is not exported to the public mirror — nothing to test here",
)


def _extract_predicate() -> str:
    """Pull the `if echo "$CHANGED" | ... ; then` line that gates the backend branch."""
    assert SCRIPT.exists(), (
        f"{SCRIPT} is gone while backend/ops/ still exists — the deploy script was "
        "moved or deleted; re-anchor this test rather than skipping it"
    )
    lines = SCRIPT.read_text().splitlines()
    hits = [
        ln.strip()
        for ln in lines
        if ln.strip().startswith("if echo \"$CHANGED\"")
        and "'^backend/'" in ln            # the backend branch, not obis/admin-panel/org-portal
    ]
    assert len(hits) == 1, (
        f"expected exactly one backend-gate line in deploy-if-new.sh, found {len(hits)}: {hits}"
    )
    # `if <pipeline>; then` -> `<pipeline>`
    return re.sub(r"^if\s+|\s*;\s*then$", "", hits[0])


def _restarts(changed: list[str]) -> bool:
    """Run the REAL predicate under bash with this list of changed paths."""
    predicate = _extract_predicate()
    # The paths are ours, but quote them the way the shell needs anyway: a single
    # quote inside a filename would otherwise end the literal and run the rest.
    body = "\n".join(changed).replace("'", "'\\''")
    script = "CHANGED='" + body + "'\n" + predicate + "\n"
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert proc.returncode in (0, 1), f"predicate errored: {proc.returncode} {proc.stderr}"
    return proc.returncode == 0


# (changed paths, must the API restart?, why)
CASES = [
    # ── must NOT restart ────────────────────────────────────────────────────
    (["backend/tests/test_public_docs_match_the_code.py"], False,
     "a test file is never imported by the running service"),
    (["backend/tests/test_a.py", "backend/tests/fixtures/onc_adcp/SCHEMA_NOTES.md"], False,
     "tests plus a fixture note — the 2026-09-11 shape"),
    (["DATA-LICENCES.md", "README.md", "docs/methods/data-passthrough.md",
      "backend/tests/test_public_docs_match_the_code.py"], False,
     "EXACTLY the 2026-09-11 commit that restarted production for nothing"),
    (["frontend/src/components/Map3D.tsx"], False, "frontend only"),
    (["docs/ops/2026-09-07-deploy-if-new.md"], False, "docs only"),
    ([], False, "nothing changed"),

    # ── MUST restart — the dangerous direction ──────────────────────────────
    (["backend/main.py"], True, "the app module itself"),
    (["backend/domains/onc.py"], True, "a domain router"),
    (["backend/schema/onc.py"], True, "DDL: migrate.py must run before the new code"),
    (["backend/requirements.txt"], True, "dependencies"),
    (["backend/ops/scripts/deploy-if-new.sh"], True,
     "ops changes still get noticed — the exclusion is deliberately narrow"),
    (["backend/tests/test_a.py", "backend/main.py"], True,
     "⛔ a test NEXT TO real code must not mask the code"),
    (["frontend/src/x.tsx", "backend/db.py"], True, "mixed commit touching backend code"),
]


@pytest.mark.parametrize("changed,expected,why", CASES,
                         ids=[c[2][:40] for c in CASES])
def test_restart_decision(changed, expected, why):
    got = _restarts(changed)
    assert got == expected, (
        f"{why}\n  changed  : {changed}\n  restarts : {got}\n  expected : {expected}"
    )


def test_the_predicate_is_executable_not_a_comment():
    """If someone 'fixes' this by writing the rule in a comment, this goes red."""
    pred = _extract_predicate()
    assert not pred.lstrip().startswith("#"), "the extracted predicate is a comment"
    assert "$CHANGED" in pred and "grep" in pred, f"unexpected predicate shape: {pred!r}"
