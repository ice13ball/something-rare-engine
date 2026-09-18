# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Cross-process-safe cache-file swap, and the staleness check that goes with it.

The backend now runs as two OS processes over the SAME `/var/cache/abyssal-*`
directories: `ABYSSAL_ROLE=worker` bakes the holdings, `ABYSSAL_ROLE=web` serves
them. Every bake→read pair that used to live inside one process is now a file
race between two, and it has exactly two failure shapes:

1. **A torn read.** A plain `np.save(path, arr)` truncates `path` and refills it.
   A reader holding `np.load(path, mmap_mode="r")` over that file does not get an
   exception — it gets garbage, or a **SIGBUS** that kills the web process
   outright. Not a theoretical risk: measured on macOS 2026-09-18 by reverting
   `bathymetry_grid_export._write_holding` to a plain `np.save` and then reading
   through a mapping taken before it. The kernel's own triage:

       Exception Type:     EXC_BAD_ACCESS (SIGBUS)
       Exception Subtype:  FS pagein error: 22 Invalid argument
       Kernel Triage:      CL - cluster_pagein past EOF

   A page fault is not catchable from Python, so the process simply dies — the
   parent pytest exited 138 and reported ZERO failures. There is no log line and
   no red test to find afterwards; that is why this is fixed at the writer. The fix is to never modify a live file: write a sibling temp file in
   the SAME directory, then `os.replace()` it over the target. `os.replace` is an
   atomic rename on POSIX, so a reader either sees the whole old file or the whole
   new one, and an already-open mapping of the old inode stays valid until the last
   reference drops.

   ⛔ The temp file must be in the same directory as the target. A rename across
   filesystems is not atomic — it degrades to copy+unlink, which reintroduces
   precisely the torn window this exists to close.

2. **A reader that never learns.** Atomicity alone is not enough. A module-level
   cache (or an mmap) created before the swap keeps pointing at the OLD inode
   forever; the web process would then serve last week's grid until someone
   restarts it, with nothing in the log to say so. In this project "works wrongly
   and says nothing" is worse than a loud failure, so every cached reader must
   re-check the file's identity and reload when it changed. `file_stamp()` is that
   check: `st_ino` catches the replace (a new inode), `st_mtime_ns` catches an
   in-place rewrite that happened to land on the same inode, and `st_size` catches
   a truncation. Two `os.stat` calls per request is cheap enough for a request path.
"""
from __future__ import annotations

import os
import pathlib
import tempfile
from typing import Callable, Iterable

__all__ = [
    "atomic_write",
    "atomic_write_bytes",
    "atomic_write_text",
    "atomic_np_save",
    "file_stamp",
]


def atomic_write(path: "str | os.PathLike[str]", write: Callable[[pathlib.Path], None]) -> None:
    """Call `write(tmp)` on a temp file beside `path`, then atomically move it into place.

    `write` receives the temp path and must have finished writing when it returns.
    The temp file is created in `path.parent` — never in the system temp dir — so
    the final `os.replace` is a same-filesystem rename and therefore atomic.
    """
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # mkstemp (not a fixed "<name>.tmp") because two processes may now be writing
    # the same target concurrently: a shared temp name lets their writes interleave
    # into one corrupt file that is then renamed into place, perfectly intact-looking.
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=target.name + ".", suffix=".tmp")
    os.close(fd)
    tmp = pathlib.Path(tmp_name)
    try:
        write(tmp)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_bytes(path: "str | os.PathLike[str]", data: bytes) -> None:
    atomic_write(path, lambda tmp: tmp.write_bytes(data))


def atomic_write_text(path: "str | os.PathLike[str]", text: str, encoding: str = "utf-8") -> None:
    atomic_write(path, lambda tmp: tmp.write_text(text, encoding=encoding))


def atomic_np_save(path: "str | os.PathLike[str]", arr) -> None:
    """`np.save` into a sibling temp file, then swap it over `path`.

    ⚠️ Written through an open file handle, not by path: `np.save` APPENDS ".npy"
    to a path that lacks it, so passing the temp path directly would make numpy
    invent a name the rename could not then find. Same trap `currents_bake.py`
    documents for `np.savez_compressed`.
    """
    import numpy as np  # lazy — this module is imported on paths that never save

    def _write(tmp: pathlib.Path) -> None:
        with open(tmp, "wb") as fh:
            np.save(fh, arr)

    atomic_write(path, _write)


def file_stamp(paths: "Iterable[str | os.PathLike[str]]") -> tuple:
    """Identity of `paths` right now: `(st_ino, st_mtime_ns, st_size)` each, `None` if absent.

    Compare a cached stamp against a fresh one to decide whether a cached/mmapped
    read is still describing the file on disk. A missing file stamps as `None`
    rather than raising, so "the bake has not run yet" and "the bake ran and the
    file was removed" are both representable and both differ from a real stamp.
    """
    out = []
    for p in paths:
        try:
            st = os.stat(p)
        except OSError:
            out.append(None)
        else:
            out.append((st.st_ino, st.st_mtime_ns, st.st_size))
    return tuple(out)
