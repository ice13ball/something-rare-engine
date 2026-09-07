# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""backend/.env.example must document every environment variable the backend reads.

A hand-maintained list drifts the first time someone adds a new `os.getenv(...)`
call — nobody remembers to also touch .env.example, and a developer cloning the
repo has no way to discover the variable exists. So this test does not hard-code
the "true" list of names; it re-derives it the same way a human audit would:
walk every backend/**/*.py file (excluding backend/tests/ — test fixtures are not
runtime config) with the `ast` module and collect every string literal passed to
os.getenv(...), os.environ.get(...), or os.environ[...]. That set is then
required to be a subset of the names declared in .env.example.

backend/scripts/ and backend/schema/ are IN SCOPE: scripts/ contains maintenance
and CI-bootstrap scripts that run against the same .env (e.g. ci_bootstrap_db.py
reading TEST_DATABASE_URL, download_kbas.py reading PGPASSWORD), and schema/ is
migration/DDL helper code, not test fixtures. Only backend/tests/ is excluded, and
_envscan.py's own directory walk enforces that exclusion — it is not re-applied
here, so this test cannot silently narrow its own exclusion.
"""
import re
from pathlib import Path

from _envscan import scan

BACKEND = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = BACKEND / ".env.example"

# Matches a declared variable at the start of a line: NAME=..., ignoring comments
# and blank lines. Deliberately does NOT try to parse shell quoting/escaping —
# .env.example lines are simple NAME=value or NAME= (optionally with a trailing
# "# comment"), never anything more complex.
_DECLARED_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=")


def _declared_names() -> set[str]:
    names = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        m = _DECLARED_RE.match(line.strip())
        if m:
            names.add(m.group(1))
    return names


def test_env_example_documents_every_discovered_variable():
    discovered, non_literal = scan()
    declared = _declared_names()

    missing = sorted(discovered - declared)
    assert not missing, (
        f"{len(missing)} environment variable(s) are read by backend code via "
        "os.getenv/os.environ but are not documented in backend/.env.example: "
        f"{missing}. Add a NAME= line (with a one-line comment explaining what "
        "breaks without it) to backend/.env.example."
    )

    # Not a hard failure: a non-literal getenv name (f-string, variable, etc.)
    # cannot be enumerated by this scanner and needs a human-written comment
    # instead of a generated line. Surface it loudly if one ever appears so a
    # reviewer notices and documents it by hand, rather than assuming coverage
    # is complete.
    assert not non_literal, (
        "found os.getenv/os.environ call(s) whose variable name is not a string "
        f"literal, so this test cannot verify they are documented: {non_literal}. "
        "Add a manual comment for these in backend/.env.example."
    )
