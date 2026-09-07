# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Turns the v2 neutral-report editorial guardrail into an enforced CI gate.

WHY THIS EXISTS: `backend/scripts/check_neutral_report.py` was written to be run by
hand ("Run manually before promoting v2 on dev"). A guard nobody runs is not a guard.
`grep` over `.github/workflows/` on 2026-08-29 found zero references to it, so nothing
stopped the forbidden vocabulary from shipping. These tests run in the existing pytest
job, so the guard now fails the build instead of relying on somebody remembering.

The vocabulary list is the point: v2 reports state measurements, never verdicts.
If a word is dropped from FORBIDDEN, the matching test here goes red — which is the
gate doing its job, not a stale test. Loosening the rule must be a deliberate edit
in two places, never a silent one.
"""
from __future__ import annotations

import json

import pytest

from backend.scripts.check_neutral_report import main, scan

# Every term the spec forbids, with the surface forms that must all be caught.
FORBIDDEN_SAMPLES = [
    "critical", "Critical", "CRITICAL",
    "severe", "alarming", "significant", "concerning", "severity",
    "risk score", "risk_score", "risk rating", "risk level", "Risk Score",
    "recommend", "recommends", "recommended", "recommendation",
]

# Neutral wording that must NOT trip the guard — a guard with false positives
# gets switched off, which is the same as having none.
NEUTRAL_SAMPLES = [
    "measured", "observed", "the value increased by 12 percent",
    "coverage", "uncertainty", "median", "sampling density",
    "risky",          # not one of the forbidden compounds
    "recommender",    # \b prevents a substring hit
]


def _report(text: str) -> dict:
    return {"id": "ARGO-12345", "version": 2, "summary": text}


@pytest.mark.parametrize("word", FORBIDDEN_SAMPLES)
def test_forbidden_vocabulary_is_caught(word):
    assert scan(json.dumps(_report(f"The trend is {word} in this basin."))), (
        f"{word!r} passed the guard — FORBIDDEN no longer covers it"
    )


@pytest.mark.parametrize("word", NEUTRAL_SAMPLES)
def test_neutral_vocabulary_passes(word):
    assert scan(json.dumps(_report(f"The {word} was recorded."))) == [], (
        f"{word!r} was flagged — the guard produces false positives"
    )


def test_main_returns_0_for_a_clean_report(tmp_path, capsys):
    p = tmp_path / "clean.json"
    p.write_text(json.dumps(_report("Median depth 812 m; coverage 94 percent.")), encoding="utf-8")
    assert main(["check_neutral_report.py", str(p)]) == 0
    assert "OK" in capsys.readouterr().out


def test_main_returns_1_and_names_the_words(tmp_path, capsys):
    p = tmp_path / "dirty.json"
    p.write_text(json.dumps(_report("A critical risk score is recommended.")), encoding="utf-8")
    assert main(["check_neutral_report.py", str(p)]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "critical" in out


def test_main_returns_2_on_non_json(tmp_path):
    # Guards the "otherwise we'd be matching against raw HTML" case in the script.
    p = tmp_path / "page.html"
    p.write_text("<html><body>critical</body></html>", encoding="utf-8")
    assert main(["check_neutral_report.py", str(p)]) == 2


def test_main_returns_2_on_wrong_arity():
    assert main(["check_neutral_report.py"]) == 2
