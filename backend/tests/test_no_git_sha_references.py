# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Guard against citing a private-history commit SHA in a shipping comment.

The public mirror (`something-rare-engine`) is published as a single fresh
commit — see `scripts/export-public.sh`. A comment that says "(see <short-sha>)"
or "fixed in <short-sha>" is a pointer to nothing for anyone reading that
mirror: `git show <short-sha>` errors, because the commit it names lived only
in this repository's private development history. A double-digit count of
such comments were found by a 2026-09 audit and rewritten to cite a date and
the change instead of a hash that cannot be followed — this guard is what
stops the next one from shipping.

Three failure modes a naive version of this guard has hit before, in this
exact repo, for adjacent guards (`test_sample_date_contract.py`,
`test_licence_notice.py`):

1. **False positives.** A bare 7-40 char lowercase-hex-shaped token is not
   automatically a commit SHA — it is also how a CSS colour literal, a
   sha256/sha1 digest quoted for licence verification, a DOI suffix, a UUID,
   and a plain decimal id (a seamount number, an int4 boundary, a WOD cast id
   — digits 0-9 are valid hex digits too) all look. `_hits_on_line` below is
   built to let all of those through; see the predicate tests at the bottom
   of this file for the constructed cases.
2. **Wrong scope.** A guard scoped to "the directory I happened to edit"
   misses the next one. This one is scoped to what actually reaches the
   public mirror: `scripts/export-public.sh`'s PUBLIC_RULES cover `backend/`
   and `frontend/` wholesale, so that is what is scanned here — including
   `frontend/seo/`, the server-rendering pipeline that every earlier
   frontend content guard in this repo missed at least once. The exact
   NEVER-listed sub-paths from that script are excluded below by name
   instead of by importing the script at runtime, because `scripts/` itself
   is one of the NEVER paths — it does not exist in the public mirror this
   test file ships to, so this test cannot depend on it being present.
3. **Grep-shaped assertions against a fixed file list.** This walks the
   filesystem at test time and reads every matching file itself; it does not
   assert against a hard-coded list of "the nine known offenders", which
   would stop protecting anything the day an offender number ten appears
   somewhere else.
"""
from __future__ import annotations

import pathlib
import re
import tokenize

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Mirrors scripts/export-public.sh's PUBLIC_RULES (backend/, frontend/) minus
# the NEVER_RULES that sit *inside* those two trees. Root-level NEVER paths
# (scripts/, docs/, admin-panel/, org-portal/, deploy/, .github/) are already
# outside backend/ and frontend/, so they need no entry here.
_SCAN_ROOTS = ("backend", "frontend")

_NEVER_PREFIXES = (
    "backend/ops/",
    "backend/blog-images/",
    "backend/tests/fixtures/seabed/",
    "backend/tests/fixtures/mosaic/",
    "backend/tests/fixtures/arctic_rivers/",
    "backend/tests/fixtures/memento/",
    "frontend/.impeccable.md",
)

# Build output and vendored code are neither authored nor shipped as source —
# scanning them would be slow, noisy, and would flag strings nobody wrote.
_SKIP_DIR_NAMES = {"node_modules", "dist", "build", "__pycache__", ".git", "venv", ".venv"}

_SCAN_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs")

# ⛔ Impact Reports v1 is the project's frozen known-good restore path — see
# CLAUDE.md: "Do not modify Impact Reports v1 (routers/reports.py, ...)". That
# freeze predates this guard, and a pre-existing short-SHA reference sits
# inside it; this is a scope exemption for THIS guard only, not a
# public/private classification (the file still ships), and it is not this
# guard's call to lift the freeze to fix a comment. Flagged for the
# maintainer instead of silently going red or silently rewriting a frozen file.
_FROZEN_RESTORE_PATH_EXEMPTIONS = ("backend/routers/reports.py",)


def _iter_public_source_files():
    for root_name in _SCAN_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in _SCAN_SUFFIXES or not path.is_file():
                continue
            if not _SKIP_DIR_NAMES.isdisjoint(path.parts):
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if any(rel.startswith(p) for p in _NEVER_PREFIXES):
                continue
            if rel in _FROZEN_RESTORE_PATH_EXEMPTIONS:
                continue
            yield path


# ---------------------------------------------------------------------------
# Extracting comment text (the claim lives IN comments, not in code or data)
# ---------------------------------------------------------------------------

def _python_comment_lines(path: pathlib.Path) -> list[tuple[int, str]]:
    """(lineno, text) for every `#` comment and triple-quoted string in a
    .py file, via the stdlib tokenizer rather than a `#`-in-a-string-prone
    regex. Triple-quoted strings are included, not just docstrings-by-ast-
    position, because the citation this guard was written to catch a repeat
    of was sitting in a plain module docstring, not a `#` comment.

    Python 3.12 (PEP 701) tokenizes an f-string's literal text as its own
    FSTRING_MIDDLE token(s) rather than folding the whole thing into one
    STRING token — an f-string SQL block (`f\"\"\"SELECT ...\"\"\"`, common in
    this codebase's asyncpg queries) would otherwise tokenize as
    FSTRING_START/MIDDLE/END and slip past the `tok.type == STRING` check
    below undetected. FSTRING_MIDDLE is scanned unconditionally, even for a
    single-quoted f-string, because the false-positive guard on `_hits_on_line`
    already carries the weight of staying quiet on ordinary code text."""
    out: list[tuple[int, str]] = []
    try:
        with path.open("rb") as f:
            for tok in tokenize.tokenize(f.readline):
                if tok.type == tokenize.COMMENT:
                    out.append((tok.start[0], tok.string))
                elif tok.type == tokenize.STRING and tok.string.lstrip("rRbBuU")[:3] in ('"""', "'''"):
                    start_line = tok.start[0]
                    for i, line in enumerate(tok.string.splitlines()):
                        out.append((start_line + i, line))
                elif tok.type == getattr(tokenize, "FSTRING_MIDDLE", None):
                    out.append((tok.start[0], tok.string))
    except (tokenize.TokenizeError, SyntaxError, IndentationError, UnicodeDecodeError):
        pass
    return out


_JS_BLOCK_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
# A negative lookbehind for ':' keeps "https://" and "http://" from being
# misread as the start of a line comment.
_JS_LINE_RE = re.compile(r"(?<!:)//.*")


def _js_comment_lines(text: str) -> list[tuple[int, str]]:
    """(lineno, text) for every // and /* */ comment (JSX {/* */} included —
    it is a plain block comment wrapped in braces) in a JS/TS file."""
    out: list[tuple[int, str]] = []
    for m in _JS_BLOCK_RE.finditer(text):
        start_line = text.count("\n", 0, m.start()) + 1
        for i, line in enumerate(m.group(0).splitlines()):
            out.append((start_line + i, line))
    # Blank out block comments (keeping newline counts intact) before hunting
    # line comments, so nothing inside a /* */ block is scanned twice.
    without_blocks = _JS_BLOCK_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    for m in _JS_LINE_RE.finditer(without_blocks):
        lineno = without_blocks.count("\n", 0, m.start()) + 1
        out.append((lineno, m.group(0)))
    return out


def _comment_lines(path: pathlib.Path) -> list[tuple[int, str]]:
    if path.suffix == ".py":
        return _python_comment_lines(path)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    return _js_comment_lines(text)


# ---------------------------------------------------------------------------
# The predicate: is this bare hex-shaped token a claim about a commit?
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
# A UUID truncated for display, e.g. `a419c8da-…` or `a419c8da-...` naming a
# dataset id without spelling out the whole thing — same shape as a full UUID
# but with the tail elided, so it needs its own strip pass before the hex
# token search or the surviving 8 chars look exactly like a short git SHA.
_TRUNCATED_ID_RE = re.compile(r"[0-9a-f]{6,12}-(?:…|\.\.\.)")
_HEX_RE = re.compile(r"[0-9a-f]{7,40}")
_PRECEDING_MARKERS = ("sha256", "sha-256", "sha1", "sha-1", "doi")


def _hits_on_line(line: str) -> list[str]:
    """Bare hex tokens on this line that read as a git commit SHA reference.

    Deliberately NOT a bare `[0-9a-f]{7,40}` regex — see the module docstring
    for the false-positive categories this has to let through. A hit needs:
    * at least one a-f letter (an all-digit run is a plain id/count — a
      seamount number, an int4 boundary, a WOD cast id — never a citation),
    * to stand alone, not glued to more alphanumerics on either side (a UUID
      segment or a longer digest would fail this once UUIDs are stripped),
    * no `#` immediately before it (a CSS colour literal),
    * no `0x` immediately before it (a hex integer literal),
    * no `sha256`/`sha1`/`doi` earlier on the same line (a quoted digest or a
      DOI suffix, both of which are legitimately hex-shaped).
    """
    working = _UUID_RE.sub("", line)
    working = _TRUNCATED_ID_RE.sub("", working)
    hits = []
    for m in _HEX_RE.finditer(working):
        token = m.group(0)
        if not re.search(r"[a-f]", token):
            continue
        start, end = m.start(), m.end()
        before = working[start - 1] if start > 0 else ""
        after = working[end] if end < len(working) else ""
        if before.isalnum() or after.isalnum():
            continue
        if before == "#":
            continue
        if working[max(0, start - 2):start] == "0x":
            continue
        context = working[:start].lower()
        if any(marker in context for marker in _PRECEDING_MARKERS):
            continue
        hits.append(token)
    return hits


# ---------------------------------------------------------------------------
# The guard itself
# ---------------------------------------------------------------------------

def test_no_shipping_comment_cites_a_private_commit_sha():
    """A comment that names a commit hash is unfollowable in the public
    mirror, which ships as one fresh commit with no history behind it. Say
    the date and the change instead — see the rewrites this guard was added
    alongside for the pattern."""
    offenders = []
    for path in _iter_public_source_files():
        for lineno, line in _comment_lines(path):
            hits = _hits_on_line(line)
            if hits:
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {hits}")
    assert offenders == [], (
        "shipping comment(s) cite a commit hash unfollowable in the public "
        f"mirror — replace with a date and the change: {offenders}"
    )


# ---------------------------------------------------------------------------
# Predicate tests — construct each false-positive category by hand
# ---------------------------------------------------------------------------

def test_predicate_flags_a_bare_short_sha():
    assert _hits_on_line("# see a1b2c3d for context") == ["a1b2c3d"]


def test_predicate_ignores_css_colour_literal():
    assert _hits_on_line("  background: #1a2b3c;  // brand navy") == []


def test_predicate_ignores_sha256_digest_in_licence_verification_comment():
    line = ("# LICENSE sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934c"
            "a495991b7852b855")
    assert _hits_on_line(line) == []


def test_predicate_ignores_doi_suffix():
    assert _hits_on_line("# see https://doi.org/10.25607/obis.occurrence.b89117cd") == []


def test_predicate_ignores_uuid():
    assert _hits_on_line("# dataset dc5abc9f-84d5-4046-a3ef-9ab24ae53756 on GBIF") == []


def test_predicate_ignores_plain_decimal_id():
    assert _hits_on_line("# cast 8539563 was truncated") == []


def test_predicate_ignores_hex_integer_literal():
    assert _hits_on_line("const FLAG = 0xdeadbee;") == []
