# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Plankton tile disk cache (no DB): paths, permissions, empty tiles, version cleanup, LRU."""
import asyncio
import os
import shutil
import stat

import pytest

from services import plankton_tiles as tiles

V1, V2 = "20261007120000-a1b2c3", "20261107120000-d4e5f6"


def test_unicode_digits_are_not_a_version():
    assert tiles.VERSION_RE.fullmatch(V1)
    assert not tiles.VERSION_RE.fullmatch("\u0662\u0660261007120000-a1b2c3")     # Arabic-Indic digits
    assert not tiles.VERSION_RE.fullmatch("\uff12\uff10261007120000-a1b2c3")     # fullwidth digits


def test_only_a_well_formed_version_and_key_reach_a_path(tmp_path):
    assert tiles.tile_path(tmp_path, V1, "all", 3, 4, 2) == tmp_path / V1 / "all" / "3" / "4" / "2.pbf"
    for version, key in ((V1 + "/..", "all"), ("../etc", "all"), (V1 + "\n", "all"), (V1, "../all"),
                         (V1, "all/x"), (V1, "G05-d140-b1-e1")):
        with pytest.raises(ValueError):
            tiles.tile_path(tmp_path, version, key, 0, 0, 0)


def test_a_written_tile_reads_back_and_an_empty_tile_is_a_hit_not_a_miss(tmp_path):
    p = tiles.tile_path(tmp_path, V1, "all", 0, 0, 0)
    assert tiles.read_cached(p) is None
    assert tiles.write_cached(p, b"\x1a\x02ab") is True
    assert tiles.read_cached(p) == b"\x1a\x02ab"
    q = tiles.tile_path(tmp_path, V1, "all", 1, 0, 0)
    assert tiles.write_cached(q, b"") is True
    assert tiles.read_cached(q) == b""


def test_a_cached_tile_is_group_readable_and_writable(tmp_path):
    p = tiles.tile_path(tmp_path, V1, "all", 0, 0, 0)
    tiles.write_cached(p, b"x")
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o664
    assert not list(p.parent.glob("*.tmp"))


def test_an_unwritable_cache_is_reported_not_raised(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_bytes(b"")
    assert tiles.write_cached(tiles.tile_path(blocker, V1, "all", 0, 0, 0), b"x") is False


def test_a_read_marks_the_tile_as_recently_used(tmp_path):
    p = tiles.tile_path(tmp_path, V1, "all", 0, 0, 0)
    tiles.write_cached(p, b"x")
    os.utime(p, (1_000_000, 1_000_000))
    tiles.read_cached(p)
    assert os.stat(p).st_mtime > 1_000_000


def test_old_versions_go_and_nothing_else_is_touched(tmp_path):
    for v in (V1, V2):
        tiles.write_cached(tiles.tile_path(tmp_path, v, "all", 0, 0, 0), b"x")
    (tmp_path / "lost+found").mkdir()
    (tmp_path / "20261007120000-zzzzzz").mkdir()
    assert tiles.drop_other_versions(tmp_path, V2) == 1
    assert sorted(c.name for c in tmp_path.iterdir()) == sorted([V2, "lost+found", "20261007120000-zzzzzz"])


def _cost(path):
    return max(os.stat(path).st_blocks * 512, 4096)


def test_prune_removes_least_recently_used_tiles_down_to_ninety_percent(tmp_path):
    paths = []
    for i in range(5):
        p = tiles.tile_path(tmp_path, V1, "all", 3, 0, i)
        tiles.write_cached(p, b"x" * 100)
        os.utime(p, (1_000 + i, 1_000 + i))
        paths.append(p)
    tiles.read_cached(paths[0])                           # used just now: must survive
    cost = _cost(paths[0])                                # each tile occupies at least one block on disk
    dirs = 4 * 4096                                       # <version>/all/3/0 count too
    cap = 3 * cost + dirs
    assert tiles.prune(tmp_path, cap_bytes=cap) == 3      # 9 blocks -> at most 7.2
    assert [p.exists() for p in paths] == [True, False, False, False, True]
    assert tiles.prune(tmp_path, cap_bytes=cap) == 0


def test_empty_tiles_count_against_the_cap_as_one_block_each(tmp_path):
    """0-byte files (cached EMPTY tiles) cost an inode and a block; counting st_size never pruned them."""
    paths = []
    for i in range(6):
        p = tiles.tile_path(tmp_path, V1, "all", 3, 0, i)
        tiles.write_cached(p, b"")
        os.utime(p, (1_000 + i, 1_000 + i))
        paths.append(p)
    assert all(os.stat(p).st_size == 0 for p in paths)
    assert tiles.prune(tmp_path, cap_bytes=3 * 4096 + 4 * 4096) > 0   # 6 tiles + 4 dirs > 7 blocks
    assert [p.exists() for p in paths][-1] is True and not paths[0].exists()


def test_a_symlink_named_like_a_version_is_never_followed_or_removed(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    (outside / "all").mkdir(parents=True)
    (outside / "all" / "precious.pbf").write_bytes(b"x")
    link = root / V1
    link.symlink_to(outside, target_is_directory=True)
    tiles.write_cached(tiles.tile_path(root, V2, "all", 0, 0, 0), b"x")
    assert tiles.drop_other_versions(root, V2) == 0
    assert link.is_symlink() and (outside / "all" / "precious.pbf").exists()


def test_prune_clears_temp_files_left_by_a_killed_writer(tmp_path):
    d = tmp_path / V1 / "all" / "0" / "0"
    d.mkdir(parents=True)
    old, fresh = d / "0.pbf.abc.tmp", d / "0.pbf.def.tmp"
    old.write_bytes(b"x")
    fresh.write_bytes(b"x")
    os.utime(old, (1_000, 1_000))
    tiles.prune(tmp_path, cap_bytes=10 ** 9)
    assert not old.exists() and fresh.exists()


async def test_every_nth_write_starts_one_background_prune(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(tiles, "PRUNE_EVERY", 2)
    monkeypatch.setattr(tiles, "_writes", 0)
    monkeypatch.setattr(tiles, "_prune_task", None)
    monkeypatch.setattr(tiles, "prune", lambda root, *a, **k: seen.append(root) or 0)
    for _ in range(4):
        tiles.note_write(tmp_path)
        await asyncio.sleep(0.05)
    assert seen == [tmp_path, tmp_path]


def test_the_cache_root_comes_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANKTON_TILE_CACHE_DIR", str(tmp_path))
    assert tiles.cache_root() == tmp_path
    monkeypatch.delenv("PLANKTON_TILE_CACHE_DIR")
    assert str(tiles.cache_root()) == "/var/cache/abyssal-plankton-tiles"


def test_new_directories_are_group_writable_even_under_a_strict_umask(tmp_path):
    old = os.umask(0o022)
    try:
        p = tiles.tile_path(tmp_path / "root", V1, "all", 2, 1, 1)
        assert tiles.write_cached(p, b"x") is True
    finally:
        os.umask(old)
    for d in (p.parent, p.parent.parent, p.parent.parent.parent, p.parent.parent.parent.parent):
        assert stat.S_IMODE(os.stat(d).st_mode) == 0o775, d


@pytest.mark.parametrize("root_mode, expected", ((0o2775, 0o2775), (0o775, 0o775)))
def test_new_directories_keep_the_roots_setgid_bit_and_add_none(tmp_path, root_mode, expected):
    root = tmp_path / "root"
    root.mkdir()
    os.chmod(root, root_mode)
    p = tiles.tile_path(root, V1, "all", 2, 1, 1)
    assert tiles.write_cached(p, b"x") is True
    for d in (p.parent, p.parent.parent, p.parent.parent.parent, p.parent.parent.parent.parent):
        assert stat.S_IMODE(os.stat(d).st_mode) == expected, d


def _empty_tiles(root, n, key="all"):
    """n distinct empty high-zoom tiles: each one makes its own <z>/<x> directories."""
    for i in range(n):
        tiles.write_cached(tiles.tile_path(root, V1, key, 12, i, 0), b"")


def test_directories_count_against_the_byte_cap(tmp_path):
    _empty_tiles(tmp_path, 10)                       # 10 files + 10 x-dirs (+ shared dirs)
    files_only = 10 * 4096
    # cap above the files alone: only counting directories can push the total over it
    assert tiles.prune(tmp_path, cap_bytes=files_only + 2 * 4096) > 0


def test_the_entry_cap_triggers_a_prune_even_when_bytes_are_small(tmp_path, monkeypatch):
    paths = []
    for i in range(8):
        p = tiles.tile_path(tmp_path, V1, "all", 3, 0, i)
        tiles.write_cached(p, b"")
        os.utime(p, (1_000 + i, 1_000 + i))
        paths.append(p)
    monkeypatch.setattr(tiles, "CACHE_MAX_ENTRIES", 6)
    assert tiles.prune(tmp_path, cap_bytes=10 ** 12) > 0
    assert not paths[0].exists() and paths[-1].exists()


def test_empty_directories_go_after_a_prune_but_root_and_version_dirs_stay(tmp_path):
    _empty_tiles(tmp_path, 5)
    (tmp_path / V2).mkdir()                          # an empty version directory
    tiles.prune(tmp_path, cap_bytes=1)               # evicts every tile
    assert tmp_path.is_dir() and (tmp_path / V1).is_dir() and (tmp_path / V2).is_dir()
    assert not any((tmp_path / V1).iterdir())        # key/z/x directories are gone


def test_temp_files_count_toward_the_totals(tmp_path):
    for i in range(2):
        tiles.write_cached(tiles.tile_path(tmp_path, V1, "all", 3, 0, i), b"")
    d = tmp_path / V1 / "all" / "3" / "0"
    for i in range(5):
        (d / f"{i}.pbf.x{i}.tmp").write_bytes(b"x")   # fresh: not removable, but they occupy disk
    # two tiles + dirs fit under the cap; only the temp files push the total over it
    assert tiles.prune(tmp_path, cap_bytes=2 * 4096 + 4 * 4096 + 2 * 4096) > 0


def test_a_directory_removed_between_mkdirs_and_write_is_a_failed_write_not_an_error(tmp_path, monkeypatch):
    p = tiles.tile_path(tmp_path, V1, "all", 3, 0, 0)
    real = tiles._mkdirs

    def mkdirs_then_prune_wins(d):
        real(d)
        shutil.rmtree(tmp_path / V1)                 # prune's rmdir pass removed what we just created
    monkeypatch.setattr(tiles, "_mkdirs", mkdirs_then_prune_wins)
    assert tiles.write_cached(p, b"x") is False      # logged, served uncached, no exception


def test_route_and_service_agree_on_the_highest_zoom():
    from domains import plankton
    assert plankton.MAX_ZOOM == tiles.TILE_MAX_ZOOM == 12


def test_empty_directories_alone_over_the_entry_cap_are_removed(tmp_path, monkeypatch):
    """Directories left by failed writes count toward the entry cap; with no file to remove they were never cleaned."""
    monkeypatch.setattr(tiles, "CACHE_MAX_ENTRIES", 5)
    base = tmp_path / V1 / "all"
    for i in range(8):
        (base / "9" / str(i)).mkdir(parents=True)
    assert tiles.prune(tmp_path, cap_bytes=10 ** 9) == 0          # no file removed ...
    assert (tmp_path / V1).is_dir() and not (base / "9").exists()  # ... yet the empty directories are gone
