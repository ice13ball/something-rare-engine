# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The deploy workflow skips its test run only when GitHub shows both test jobs green.

A wrong `true` ships untested code, so the cases below are the ways it could go wrong:
a red run hiding behind a green one, a job still running, one of the two jobs missing,
the deploy run counting its own check runs, and a manual dispatch skipping the suite.
"""
import io
import json
from pathlib import Path

import pytest

from backend.scripts import ci_already_green as g

BE, FE = g.REQUIRED_JOBS


def run(name, conclusion="success", status="completed", run_id="100"):
    url = f"https://github.com/o/r/actions/runs/{run_id}/job/9"
    return {"name": name, "status": status, "conclusion": conclusion,
            "html_url": url, "details_url": url}


def green(run_id="100", prefix=""):
    return [run(prefix + BE, run_id=run_id), run(prefix + FE, run_id=run_id)]


def test_required_names_match_the_jobs_in_tests_yml():
    """The names are copied from the workflow; a rename there must fail here, not silently."""
    text = (Path(__file__).resolve().parents[2] / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    for job in g.REQUIRED_JOBS:
        assert f"name: {job}" in text


@pytest.mark.parametrize("prefix", ["", "test / "])
def test_green_with_or_without_the_workflow_call_prefix(prefix):
    assert g.decide(green(prefix=prefix))[0] is True


def test_dev_shape_standalone_cancelled_plus_called_green():
    runs = [run(BE, "cancelled", run_id="1"), run(FE, "cancelled", run_id="1"),
            run("test / " + BE, run_id="2"), run("test / " + FE, run_id="2")]
    assert g.decide(runs)[0] is True


def test_mixed_halves_from_different_runs_are_enough():
    assert g.decide([run(BE, run_id="1"), run("test / " + FE, run_id="2")])[0] is True


def test_one_red_run_beats_a_green_one():
    runs = green(run_id="1") + [run("test / " + BE, "failure", run_id="2")]
    ok, why = g.decide(runs)
    assert ok is False and "red" in why


@pytest.mark.parametrize("bad", ["failure", "timed_out", "action_required", "startup_failure"])
def test_every_bad_conclusion_blocks(bad):
    assert g.decide(green() + [run(FE, bad, run_id="2")])[0] is False


@pytest.mark.parametrize("meh", ["cancelled", "skipped", "neutral"])
def test_cancelled_skipped_neutral_do_not_count_as_red(meh):
    assert g.decide(green() + [run(FE, meh, run_id="2")])[0] is True


def test_only_cancelled_is_not_green():
    runs = [run(BE, "cancelled"), run(FE, "cancelled")]
    assert g.decide(runs)[0] is False


def test_one_job_missing_is_not_green():
    ok, why = g.decide([run(BE)])
    assert ok is False and "Frontend" in why


def test_job_still_running_is_not_green():
    runs = [run(BE), run(FE, conclusion=None, status="in_progress")]
    assert g.decide(runs)[0] is False


def test_no_check_runs_is_not_green():
    assert g.decide([])[0] is False


def test_lint_is_ignored_both_ways():
    lint_red = run("test / Lint — report only, never blocks", "failure")
    assert g.decide(green() + [lint_red])[0] is True
    assert g.decide([run("test / Lint — report only, never blocks")])[0] is False


def test_similar_names_do_not_match():
    runs = [run("Backend — pytest against a fresh PostGIS (copy)"), run("xBackend — pytest against a fresh PostGIS"), run(FE)]
    assert g.decide(runs)[0] is False


def test_own_run_is_excluded():
    # Its own red attempt must not count, and its own green must not count as proof.
    own_green = green(run_id="777")
    assert g.decide(own_green, own_run_id="777")[0] is False
    assert g.decide(green(run_id="1") + [run(BE, "failure", run_id="777")], own_run_id="777")[0] is True


def test_run_id_prefix_is_not_confused_with_a_longer_id():
    assert g.decide(green(run_id="1234"), own_run_id="123")[0] is True


def test_workflow_dispatch_never_skips():
    ok, why = g.decide(green(), event="workflow_dispatch")
    assert ok is False and "manual" in why
    assert g.decide(green(), event="push")[0] is True


def _cli(monkeypatch, capsys, payload, *argv):
    monkeypatch.setattr("sys.stdin", io.StringIO(payload if isinstance(payload, str) else json.dumps(payload)))
    assert g.main(list(argv)) == 0
    return capsys.readouterr().out.strip()


def test_cli_prints_the_output_line_for_one_page_and_for_slurped_pages(monkeypatch, capsys):
    page = {"total_count": 2, "check_runs": green()}
    assert _cli(monkeypatch, capsys, page) == "already_green=true"
    assert _cli(monkeypatch, capsys, [{"check_runs": [green()[0]]}, {"check_runs": [green()[1]]}]) == "already_green=true"
    assert _cli(monkeypatch, capsys, {"check_runs": []}) == "already_green=false"


def test_cli_fails_safe_on_garbage(monkeypatch, capsys):
    for bad in ("", "not json", "null", "{}", '{"check_runs": 3}', '{"message": "Not Found"}'):
        assert _cli(monkeypatch, capsys, bad) == "already_green=false", bad
