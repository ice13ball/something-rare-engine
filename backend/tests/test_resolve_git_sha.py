# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""resolve_git_sha() must work without a `git` subprocess.

Production incident (2026-09): the abyssal-api systemd unit sets `PATH` to
just the venv's bin/ (deliberately, so the venv's python/uvicorn win over any
system copy). `git` is not on that PATH, so the old subprocess-only
resolve_git_sha() raised FileNotFoundError on every boot, was swallowed by
its own except clause, and silently returned None forever. schema_migrations
held the running commit the whole time; /health just could never confirm it
— "unknown" instead of "ok", permanently, and no test caught it because every
test runs somewhere `git` IS on PATH.

The fix reads `.git` directly (`_read_git_head_sha`) before ever touching a
subprocess. This file tests that reader against on-disk fixtures built with
`tmp_path`, and then — the case that actually proves the incident cannot
recur — runs the real resolver in a subprocess whose PATH has no `git` on it
at all.
"""
import os
import pathlib
import subprocess
import sys

import pytest

from schema_steps import _read_git_head_sha, resolve_git_sha

BACKEND = pathlib.Path(__file__).resolve().parent.parent

SHA_A = "a" * 40
SHA_B = "b" * 40


def test_raw_sha_in_head(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text(SHA_A + "\n")
    assert _read_git_head_sha(tmp_path) == SHA_A


def test_ref_with_loose_ref_file(tmp_path):
    gitdir = tmp_path / ".git"
    gitdir.mkdir()
    (gitdir / "HEAD").write_text("ref: refs/heads/dev\n")
    refs_heads = gitdir / "refs" / "heads"
    refs_heads.mkdir(parents=True)
    (refs_heads / "dev").write_text(SHA_A + "\n")
    assert _read_git_head_sha(tmp_path) == SHA_A


def test_ref_only_in_packed_refs(tmp_path):
    """Same ref as above, but no loose refs/heads/dev file — only packed-refs
    knows it, which is what a `git gc` leaves behind."""
    gitdir = tmp_path / ".git"
    gitdir.mkdir()
    (gitdir / "HEAD").write_text("ref: refs/heads/dev\n")
    (gitdir / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled sorted\n"
        f"{SHA_B} refs/heads/dev\n"
        f"{SHA_A} refs/heads/main\n"
    )
    assert _read_git_head_sha(tmp_path) == SHA_B


def test_worktree_pointer_file(tmp_path):
    """A `.git` FILE (worktree pointer: `gitdir: <path>`), not a directory."""
    real_gitdir = tmp_path / "real-gitdir"
    real_gitdir.mkdir()
    (real_gitdir / "HEAD").write_text(SHA_A + "\n")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {real_gitdir}\n")
    assert _read_git_head_sha(worktree) == SHA_A


def test_no_git_at_all_and_no_env_var_is_none(tmp_path, monkeypatch):
    monkeypatch.delenv("ABYSSAL_GIT_SHA", raising=False)
    assert _read_git_head_sha(tmp_path) is None


def test_env_var_wins_over_disk(monkeypatch):
    """ABYSSAL_GIT_SHA short-circuits before any .git is even looked at —
    checked against the real repo checkout, which does have a real .git."""
    monkeypatch.setenv("ABYSSAL_GIT_SHA", "envwins" * 5)
    assert resolve_git_sha() == "envwins" * 5


# ── The case that actually proves the production bug cannot recur ──────────

def _real_head_sha() -> str:
    out = subprocess.run(["git", "-C", str(BACKEND), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=10, check=True)
    return out.stdout.strip()


def test_resolves_without_git_on_path(tmp_path):
    """Reproduces the systemd unit's environment exactly: PATH points only at
    a directory with no `git` binary in it. Before this fix, resolve_git_sha()
    called `subprocess.run(["git", ...])` unconditionally, PATH lookup failed
    with FileNotFoundError, and the function returned None — this is the
    check that would have failed on the old code and caught the incident
    before it reached production.
    """
    empty_bin = tmp_path / "no-git-here"
    empty_bin.mkdir()

    env = os.environ.copy()
    env["PATH"] = str(empty_bin)
    env.pop("ABYSSAL_GIT_SHA", None)

    code = "import schema_steps; print(schema_steps.resolve_git_sha() or '')"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    resolved = result.stdout.strip()
    assert resolved, (
        f"resolve_git_sha() returned nothing with git off PATH — the exact "
        f"shape of the production incident. stderr={result.stderr}"
    )
    assert resolved == _real_head_sha()
