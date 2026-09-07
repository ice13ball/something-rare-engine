# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Editorial guardrail for v2 neutral impact reports.

Scans a JSON file for forbidden verdict vocabulary. Exits 0 if clean,
1 if any forbidden word appears. Run manually before promoting v2
on dev, and against VPS-cached v2 reports after deploy.

Usage:
    python3 -m backend.scripts.check_neutral_report path/to/report.json
    curl https://.../v2/reports/impact/ARGO-12345 | python3 -m backend.scripts.check_neutral_report -

The forbidden regex enforces the spec's "no interpretation" rule.
"""
from __future__ import annotations

import json
import re
import sys

FORBIDDEN = re.compile(
    r"\b("
    r"critical|severe|alarming|significant|concerning|"
    r"risk[_ ]?(score|rating|level)|severity|"
    r"recommend(ed|s|ation)?"
    r")\b",
    re.IGNORECASE,
)


def scan(payload_text: str) -> list[str]:
    """Return a list of forbidden matches found in the payload text."""
    return [m.group(0) for m in FORBIDDEN.finditer(payload_text)]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_neutral_report.py <path-or-dash-for-stdin>", file=sys.stderr)
        return 2

    src = argv[1]
    text = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()

    # Validate it parses as JSON — otherwise we'd be matching against raw HTML.
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"input is not valid JSON: {exc}", file=sys.stderr)
        return 2

    matches = scan(text)
    if matches:
        print(f"FAIL: found {len(matches)} forbidden verdict word(s): {sorted(set(matches))}")
        return 1

    print("OK: no verdict vocabulary detected")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
