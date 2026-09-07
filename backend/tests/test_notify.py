# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import asyncio
import os
import stat
import pytest

from api_access import notify


def test_missing_script_returns_false(tmp_path):
    missing = str(tmp_path / "nope.sh")
    assert asyncio.run(notify.notify_telegram("hi", script=missing)) is False


def test_real_script_invoked_with_args(tmp_path):
    out = tmp_path / "out.txt"
    script = tmp_path / "fake_notify.sh"
    script.write_text(f'#!/usr/bin/env bash\nprintf "%s|%s" "$1" "$2" > "{out}"\nexit 0\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXUSR)
    ok = asyncio.run(notify.notify_telegram("body-msg", "the-title", script=str(script)))
    assert ok is True
    assert out.read_text() == "body-msg|the-title"


def test_failing_script_returns_false(tmp_path):
    script = tmp_path / "fail.sh"
    script.write_text('#!/usr/bin/env bash\nexit 3\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXUSR)
    assert asyncio.run(notify.notify_telegram("x", script=str(script))) is False


def test_unset_env_is_reported_as_unset(monkeypatch, caplog):
    """An unconfigured helper must say it is unconfigured.

    Before NOTIFY_SCRIPT was required, the default pointed at one maintainer's
    home directory. On every other host that path simply did not exist, so the
    alert took the "script not found" branch — indistinguishable in the log from
    a deployment whose helper had been moved or deleted.
    """
    monkeypatch.delenv("NOTIFY_SCRIPT", raising=False)
    with caplog.at_level("WARNING"):
        assert asyncio.run(notify.notify_telegram("x")) is False
    assert "NOTIFY_SCRIPT is unset" in caplog.text


def test_env_var_is_used_when_no_script_argument(tmp_path, monkeypatch):
    out = tmp_path / "env.txt"
    script = tmp_path / "from_env.sh"
    script.write_text(f'#!/usr/bin/env bash\nprintf "%s" "$1" > "{out}"\nexit 0\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXUSR)
    monkeypatch.setenv("NOTIFY_SCRIPT", str(script))
    assert asyncio.run(notify.notify_telegram("via-env")) is True
    assert out.read_text() == "via-env"
