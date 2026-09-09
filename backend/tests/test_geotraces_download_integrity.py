# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""fetch_and_extract must never hand a short download on to the parser.

Measured against the live BODC endpoint 2026-09-09: three of four plain
transfers of the 260 MB IDP2025 archive died mid-stream with
`OpenSSL SSL_read: ... unexpected eof while reading` (curl exit 56), the
last at 240,136,841 of 259,969,623 bytes. BODC serves a Content-Length but
rejects Range, so a retry restarts the transfer rather than resuming it.

Two guarantees here, both of which have to be able to fail:
  - the transfer is retried, or the sync dies on a transient TLS drop
  - a short file is named as a truncation, not passed to zipfile to surface
    three frames later as an uninformative BadZipFile
"""
import json
import os
import subprocess

import pytest

from ingestion import geotraces_ingest as gt


def _fake_curl(*, head_len: int | None, written: int):
    """Stand in for both curl invocations: the HEAD probe and the download."""
    calls: list[list[str]] = []

    def run(cmd, *a, **kw):
        calls.append(cmd)
        if "-I" in cmd:
            hdrs = {} if head_len is None else {"content-length": [str(head_len)]}
            return subprocess.CompletedProcess(
                cmd, 0, stdout=f"0\n{json.dumps(hdrs)}", stderr="")
        out = cmd[cmd.index("-o") + 1]
        with open(out, "wb") as f:
            f.write(b"\0" * written)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return run, calls


def test_truncated_download_is_named_as_such_not_passed_to_zipfile(tmp_path, monkeypatch):
    run, _ = _fake_curl(head_len=259_969_623, written=240_136_841 // 1000)
    monkeypatch.setattr(gt.subprocess, "run", run)

    with pytest.raises(RuntimeError) as exc:
        gt.fetch_and_extract(str(tmp_path))

    msg = str(exc.value)
    assert "truncated" in msg, f"the truncation was not named: {msg}"
    assert "259969623" in msg, f"the expected size is missing from the message: {msg}"
    # ⛔ Nothing may be handed downstream. If this ever becomes a BadZipFile
    # instead, the operator is debugging a corrupt archive rather than a
    # dropped transfer.
    assert not isinstance(exc.value, gt.zipfile.BadZipFile)


def test_full_length_download_passes_the_size_check(tmp_path, monkeypatch):
    """The guard must not fire on a good transfer — it stops at zipfile instead."""
    run, _ = _fake_curl(head_len=4096, written=4096)
    monkeypatch.setattr(gt.subprocess, "run", run)

    with pytest.raises(gt.zipfile.BadZipFile):
        gt.fetch_and_extract(str(tmp_path))


def test_missing_content_length_skips_the_check_rather_than_inventing_a_floor(tmp_path, monkeypatch):
    """No header means no expectation. A guessed threshold would be worse than none."""
    run, _ = _fake_curl(head_len=None, written=10)
    monkeypatch.setattr(gt.subprocess, "run", run)

    with pytest.raises(gt.zipfile.BadZipFile):
        gt.fetch_and_extract(str(tmp_path))


def test_the_download_command_carries_retry_flags(tmp_path, monkeypatch):
    """⛔ Assert on the ARGV curl is actually handed, never on the source text.

    The first version of this test grepped the function body for "--retry".
    The explanatory comment directly above the call also contains "--retry"
    and "--retry-all-errors", so deleting both flags from the command left
    the test green. It tested the prose.
    """
    run, calls = _fake_curl(head_len=4096, written=4096)
    monkeypatch.setattr(gt.subprocess, "run", run)

    with pytest.raises(gt.zipfile.BadZipFile):
        gt.fetch_and_extract(str(tmp_path))

    download = [c for c in calls if "-I" not in c]
    assert len(download) == 1, f"expected exactly one download call, got {calls}"
    argv = download[0]
    assert "--retry" in argv, (
        f"the download has no retry — a mid-stream TLS drop kills the sync: {argv}")
    assert "--retry-all-errors" in argv, (
        "curl does not treat a mid-stream TLS drop (exit 56) as retryable without "
        f"--retry-all-errors, so plain --retry would not cover the observed failure: {argv}")
