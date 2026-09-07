# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""The cache clear must not need to own /var/cache."""
from pathlib import Path

import disk_cache


def test_empty_dir_removes_contents_but_keeps_the_directory(tmp_path):
    (tmp_path / "9").mkdir()
    (tmp_path / "9" / "3.png").write_bytes(b"tile")
    (tmp_path / "loose.png").write_bytes(b"tile")

    disk_cache.empty_dir(str(tmp_path))

    assert tmp_path.is_dir(), "the directory itself must survive — removing it needs the parent"
    assert list(tmp_path.iterdir()) == []


def test_missing_directory_is_not_an_error(tmp_path):
    disk_cache.empty_dir(str(tmp_path / "never-created"))
