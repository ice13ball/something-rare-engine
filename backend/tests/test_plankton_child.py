# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""The extract runs in a child process, one per dataset (memory isolation) — no database needed."""
import asyncio
import os
import pathlib
import subprocess
import sys
import time

import duckdb
import pytest

from ingestion import plankton_obis as p

BACKEND = pathlib.Path(__file__).resolve().parent.parent
FIX = pathlib.Path(__file__).parent / "fixtures" / "plankton_obis" / "occurrences.parquet"


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _fake_child(monkeypatch, code: str):
    monkeypatch.setattr(p, "_child_argv", lambda: [sys.executable, "-c", code])


async def test_the_real_child_extracts_one_dataset_and_reports_rows_and_peak_rss(tmp_path):
    rows, peak = await p.extract_in_child(str(FIX), tmp_path / "o.parquet", tmp_path)
    expected = duckdb.sql(f"SELECT count(*) FROM read_parquet('{FIX}') WHERE ({p.GROUP_SQL}) IS NOT NULL").fetchone()[0]
    assert rows == expected > 0 and peak > 0
    assert duckdb.sql(f"SELECT count(*) FROM read_parquet('{tmp_path / 'o.parquet'}')").fetchone()[0] == rows


async def test_a_child_reporting_an_exception_fails_with_its_type_only(tmp_path):
    with pytest.raises(p.ChildFailed) as e:
        await p.extract_in_child(str(tmp_path / "SECRET-missing.parquet"), tmp_path / "o.parquet", tmp_path)
    assert "exit code 1" in e.value.reason and "SECRET" not in e.value.reason       # type, never the message/URL


async def test_a_killed_child_fails_with_the_signal(tmp_path, monkeypatch):
    _fake_child(monkeypatch, "import os, signal; os.kill(os.getpid(), signal.SIGKILL)")     # what the OOM killer does
    with pytest.raises(p.ChildFailed, match="signal 9"):
        await p.extract_in_child("x", tmp_path / "o.parquet", tmp_path)


async def test_a_nonzero_exit_without_a_report_fails_with_the_exit_code(tmp_path, monkeypatch):
    _fake_child(monkeypatch, "import sys; sys.exit(7)")
    with pytest.raises(p.ChildFailed, match="exit code 7"):
        await p.extract_in_child("x", tmp_path / "o.parquet", tmp_path)


async def test_exit_zero_without_a_result_is_a_failure(tmp_path, monkeypatch):
    _fake_child(monkeypatch, "print('hello')")
    with pytest.raises(p.ChildFailed, match="no result"):
        await p.extract_in_child("x", tmp_path / "o.parquet", tmp_path)


async def test_a_hung_child_is_killed_at_the_timeout(tmp_path, monkeypatch):
    pidfile = tmp_path / "pid"
    _fake_child(monkeypatch, f"import os, time; open({str(pidfile)!r}, 'w').write(str(os.getpid())); time.sleep(120)")
    t = time.monotonic()
    with pytest.raises(p.ChildFailed, match="timeout"):
        await p.extract_in_child("x", tmp_path / "o.parquet", tmp_path, timeout=1.5)
    assert time.monotonic() - t < 15
    assert _gone(int(pidfile.read_text()))                # no zombie left eating the cgroup


async def test_cancelling_the_parent_kills_the_child(tmp_path, monkeypatch):
    pidfile = tmp_path / "pid"
    _fake_child(monkeypatch, f"import os, time; open({str(pidfile)!r}, 'w').write(str(os.getpid())); time.sleep(120)")
    task = asyncio.create_task(p.extract_in_child("x", tmp_path / "o.parquet", tmp_path))
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text():
            break
        await asyncio.sleep(0.1)
    pid = int(pidfile.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _gone(pid)


def test_the_child_entry_does_not_pull_in_the_database_or_schema_packages():
    """Import side effects (schema package -> db, domains.*, asyncpg) are exactly what a fresh child must not pay for."""
    code = ("import sys, ingestion.plankton_extract_child, ingestion.plankton_extract as x; "
            "print(sorted(m for m in ('schema', 'db', 'asyncpg', 'api_access', 'sync_log', 'main') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "[]", out.stderr or out.stdout
