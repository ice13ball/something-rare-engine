# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Decide whether a commit already passed both test jobs, so a deploy need not re-run them.

Used by the first job of `.github/workflows/deploy-gcp.yml`. A release is tested on
`dev`; the fast-forward push of the SAME commit to `main` then used to run the whole
suite a second time before deploying. Free Actions minutes are limited, so the deploy
asks GitHub whether the tests for this exact SHA are already green and skips them if so.

Input (stdin): the JSON of `GET /repos/{owner}/{repo}/commits/{sha}/check-runs`,
either one page or a list of pages (`gh api --paginate --slurp`).
Output (stdout): one line, `already_green=true` or `already_green=false`, ready to be
appended to `$GITHUB_OUTPUT`. The reason goes to stderr.

⛔ THE RULE MIRRORS THE MAINTAINER'S LOCAL PUSH GUARD (which lets `dev` reach `main`), on purpose:
each of the two jobs needs >= 1 completed `success`, and ONE failing run of either job
(also timed_out / action_required / startup_failure) beats every green one.
cancelled / skipped / neutral count for nothing either way — the standalone `Tests`
run of a dev push is normally cancelled (the deploy calls the suite through
workflow_call, where the same jobs are prefixed `test / `), and that must not read as red.

⚠️ FAIL SAFE: anything unclear — unreadable input, an API error, a job still running —
answers `false`, which means "run the tests". The only cost of a wrong `false` is the
minutes this script exists to save; a wrong `true` would deploy untested code.

⚠️ This script reads no environment variables on purpose: `test_env_example_completeness`
requires every `os.getenv` in backend/ to be documented in `.env.example`, and a CI-only
name does not belong there. The workflow passes everything as arguments.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

# The jobs of .github/workflows/tests.yml that gate a deploy. The lint job is
# deliberately absent: it is report-only and never blocks.
REQUIRED_JOBS = (
    "Backend — pytest against a fresh PostGIS",
    "Frontend — typecheck + vitest",
)
BAD_CONCLUSIONS = frozenset({"failure", "timed_out", "action_required", "startup_failure"})

_RUN_ID_RE = re.compile(r"/actions/runs/(\d+)")


def _run_id(check_run: dict) -> str | None:
    """The workflow-run id a check run belongs to, from its job URL (None if not an Actions job)."""
    for key in ("html_url", "details_url"):
        m = _RUN_ID_RE.search(check_run.get(key) or "")
        if m:
            return m.group(1)
    return None


def _is_job(check_run: dict, job: str) -> bool:
    """Plain job name, or the same job called through workflow_call (`test / <name>`)."""
    name = check_run.get("name") or ""
    return name == job or name.endswith(" / " + job)


def decide(check_runs: list[dict], own_run_id: str | None = None,
           event: str | None = None) -> tuple[bool, str]:
    """(already_green, reason). `own_run_id` excludes the calling run's own check runs."""
    if event == "workflow_dispatch":
        return False, "manual dispatch always runs the tests"
    own = str(own_run_id) if own_run_id else None
    runs = [r for r in check_runs if own is None or _run_id(r) != own]

    missing = []
    for job in REQUIRED_JOBS:
        mine = [r for r in runs if _is_job(r, job)]
        if any(r.get("conclusion") in BAD_CONCLUSIONS for r in mine):
            return False, f"'{job}' has a red run for this commit"
        if not any(r.get("status") == "completed" and r.get("conclusion") == "success"
                   for r in mine):
            missing.append(job)
    if missing:
        return False, "no completed success yet for: " + ", ".join(missing)
    return True, "both test jobs already succeeded for this commit"


def _check_runs_from(payload) -> list[dict]:
    """Accept one page (`{"check_runs": [...]}`) or a list of pages."""
    pages = payload if isinstance(payload, list) else [payload]
    runs: list[dict] = []
    for page in pages:
        found = page["check_runs"]  # KeyError/TypeError on a malformed payload -> caught in main
        if not isinstance(found, list):
            raise TypeError("check_runs is not a list")
        runs.extend(found)
    return runs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", default=None, help="id of the calling workflow run (github.run_id)")
    ap.add_argument("--event", default=None, help="triggering event (github.event_name)")
    args = ap.parse_args(argv)
    try:
        runs = _check_runs_from(json.load(sys.stdin))
        green, reason = decide(runs, args.run_id, args.event)
    except Exception as exc:  # noqa: BLE001 — fail safe: any doubt means "run the tests"
        green, reason = False, f"could not read the check runs ({type(exc).__name__}: {exc})"
    print(f"already_green={'true' if green else 'false'}")
    print(f"ci_already_green: {reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
