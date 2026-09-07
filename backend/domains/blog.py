# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Blog — public read API, admin CRUD, and the startup seed.

Moved verbatim out of backend/main.py (Task 3 of the backend vertical-split
refactor — the first domain that owns caches the admin sweep actually clears:
`_blog_list_cache` and `_blog_article_cache` were 2 of the 9 caches
hand-cleared in `admin_cache_clear`; they are now reached only through this
module's `clear_caches()` via the Task-1 registry). Only permitted edits
applied: `@app.<method>` -> `@router.<method>`, `_pool.acquire()` ->
`db.pool.acquire()`, `_Path(__file__).parent` -> `.parent.parent` (this module
now lives one directory deeper than main.py, so `blog-images/` needs the extra
`.parent` to still resolve to `backend/blog-images/`), `_require_admin_token`
-> `require_admin_token` (dropping the underscore to match the name this leaf
already exports), and imports/docstring.

**Three distinct auth postures, preserved exactly:**
- `GET /v1/blog/articles`, `GET /v1/blog/articles/{slug}` — `Depends(get_api_key)`
- The 7 `/admin/blog/*` endpoints — `Depends(require_admin_token)`
- `GET /v1/blog/images/{filename}` — **no dependency at all, deliberately
  unauthenticated** (cover images are public assets). Do not add one.

**`ADMIN_DASHBOARD_TOKEN` / `require_admin_token` live in `auth.py`, not here**
— they are shared infrastructure (14 call sites across main.py before this
task), and `auth.py` is the leaf that already hosts `get_api_key`. See that
module's docstring for the token-rotation hazard this avoids: the rotation
endpoint in `admin_layers_api.py` rebinds `auth.ADMIN_DASHBOARD_TOKEN` at
runtime, so any reader of the token must read it through `auth`, never a name
copied into another module's namespace.

`seed_blog_if_empty` was moved here from `schema.py` (Phase 1 had parked it
there only because it runs mid-sequence inside `ensure_schema`, on the same
connection, between two DDL blocks touching `blog_articles`). `schema.py` now
imports it from here; the call site, connection, and ordering inside
`ensure_schema` are unchanged. This module does not import `schema`, so the
resulting `schema -> domains.blog` edge does not create a cycle.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from datetime import date as _date_type
from pathlib import Path as _Path

import db
from auth import get_api_key, require_admin_token
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from indexnow import notify_indexnow as _notify_indexnow, SITE_HOST

log = logging.getLogger(__name__)
router = APIRouter()

# ── Caches ──────────────────────────────────────────────────────────────────
_blog_list_cache: str | None = None
_blog_article_cache: dict[str, str] = {}


def clear_caches() -> None:
    """Drop this domain's cached responses. Called by /admin/cache/clear."""
    global _blog_list_cache
    _blog_list_cache = None
    _blog_article_cache.clear()


# ── Startup seed ────────────────────────────────────────────────────────────

async def seed_blog_if_empty(conn) -> None:
    count = await conn.fetchval("SELECT COUNT(*) FROM blog_articles")
    if count > 0:
        return
    from ingestion.blog_seed import SEED_ARTICLES
    await conn.executemany(
        """INSERT INTO blog_articles
           (slug, title, description, content_md, tags, reading_time_min, published, published_at, ai_generated)
           VALUES ($1, $2, $3, $4, $5, $6, TRUE, $7, TRUE)
           ON CONFLICT (slug) DO NOTHING""",
        [
            (
                a["slug"], a["title"], a["description"], a["content_md"],
                a["tags"], a["reading_time_min"],
                _date_type.fromisoformat(a["published_at"]),
            )
            for a in SEED_ARTICLES
        ],
    )
    log.info("blog_articles: seeded %d articles", len(SEED_ARTICLES))


# ── Blog public API ───────────────────────────────────────────────────────────

@router.get("/v1/blog/articles", dependencies=[Depends(get_api_key)])
async def blog_list():
    global _blog_list_cache
    if _blog_list_cache:
        return Response(content=_blog_list_cache, media_type="application/json")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT slug, title, description, tags, reading_time_min,
                      published_at::text AS published_at, ai_generated, cover_image
               FROM blog_articles
               WHERE published = TRUE
               ORDER BY published_at DESC"""
        )
    data = _json.dumps([dict(r) for r in rows])
    _blog_list_cache = data
    return Response(content=data, media_type="application/json")


@router.get("/v1/blog/articles/{slug}", dependencies=[Depends(get_api_key)])
async def blog_article(slug: str):
    if slug in _blog_article_cache:
        return Response(content=_blog_article_cache[slug], media_type="application/json")
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT slug, title, description, content_md, tags, reading_time_min,
                      published_at::text AS published_at, ai_generated, cover_image
               FROM blog_articles
               WHERE slug = $1 AND published = TRUE""",
            slug,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Article not found")
    data = _json.dumps(dict(row))
    _blog_article_cache[slug] = data
    return Response(content=data, media_type="application/json")


# ── Blog admin CRUD ───────────────────────────────────────────────────────────

def _clear_blog_cache(slug: str | None = None) -> None:
    global _blog_list_cache
    _blog_list_cache = None
    if slug:
        _blog_article_cache.pop(slug, None)
    else:
        _blog_article_cache.clear()


@router.get("/admin/blog/articles/{slug}", dependencies=[Depends(require_admin_token)])
async def admin_blog_get(slug: str):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT slug, title, description, content_md, tags, reading_time_min,
                      published, published_at::text, created_at::text, updated_at::text,
                      cover_image
               FROM blog_articles WHERE slug = $1""",
            slug,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Article not found")
    return Response(content=_json.dumps(dict(row)), media_type="application/json")


@router.get("/admin/blog/articles", dependencies=[Depends(require_admin_token)])
async def admin_blog_list():
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, slug, title, description, tags, reading_time_min,
                      published, published_at::text, created_at::text, updated_at::text,
                      cover_image
               FROM blog_articles ORDER BY published_at DESC NULLS LAST, created_at DESC"""
        )
    return Response(content=_json.dumps([dict(r) for r in rows]), media_type="application/json")


@router.post("/admin/blog/articles", dependencies=[Depends(require_admin_token)])
async def admin_blog_create(body: dict):
    slug = body.get("slug", "").strip()
    if not slug:
        raise HTTPException(status_code=400, detail="slug is required")
    async with db.pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """INSERT INTO blog_articles
                   (slug, title, description, content_md, tags, reading_time_min, published, published_at, cover_image)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                   RETURNING id, slug""",
                slug,
                body.get("title", ""),
                body.get("description", ""),
                body.get("content_md", ""),
                body.get("tags", []),
                body.get("reading_time_min", 5),
                bool(body.get("published", False)),
                (_date_type.fromisoformat(body["published_at"]) if body.get("published_at") else None),
                body.get("cover_image"),
            )
        except Exception as e:
            raise HTTPException(status_code=409, detail=f"Slug already exists: {e}")
    _clear_blog_cache(slug)
    return {"id": row["id"], "slug": row["slug"]}


@router.put("/admin/blog/articles/{slug}", dependencies=[Depends(require_admin_token)])
async def admin_blog_update(slug: str, body: dict):
    async with db.pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE blog_articles SET
               title            = $2,
               description      = $3,
               content_md       = $4,
               tags             = $5,
               reading_time_min = $6,
               published        = $7,
               published_at     = $8,
               cover_image      = $9,
               updated_at       = NOW()
               WHERE slug = $1""",
            slug,
            body.get("title", ""),
            body.get("description", ""),
            body.get("content_md", ""),
            body.get("tags", []),
            body.get("reading_time_min", 5),
            bool(body.get("published", False)),
            (_date_type.fromisoformat(body["published_at"]) if body.get("published_at") else None),
            body.get("cover_image"),
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Article not found")
    _clear_blog_cache(slug)
    return {"status": "updated", "slug": slug}


@router.delete("/admin/blog/articles/{slug}", dependencies=[Depends(require_admin_token)])
async def admin_blog_delete(slug: str):
    async with db.pool.acquire() as conn:
        result = await conn.execute("DELETE FROM blog_articles WHERE slug = $1", slug)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Article not found")
    _clear_blog_cache(slug)
    return {"status": "deleted", "slug": slug}


_BLOG_IMAGES_DIR = _Path(__file__).resolve().parent.parent / "blog-images"
_BLOG_IMAGES_DIR.mkdir(exist_ok=True)


@router.get("/v1/blog/images/{filename}")
async def blog_image(filename: str):
    """Serve a blog cover image by filename (e.g. what-is-deep-sea-mining.webp)."""
    path = _BLOG_IMAGES_DIR / filename
    if not path.is_file() or not path.resolve().is_relative_to(_BLOG_IMAGES_DIR.resolve()):
        raise HTTPException(status_code=404, detail="Image not found")
    suffix = path.suffix.lower()
    media = {"webp": "image/webp", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
    return FileResponse(path, media_type=media.get(suffix.lstrip("."), "application/octet-stream"),
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.post("/admin/blog/articles/{slug}/image", dependencies=[Depends(require_admin_token)])
async def admin_blog_upload_image(slug: str, file: UploadFile = File(...)):
    """Upload a cover image for a blog article. Stores as blog-images/{slug}.{ext}."""
    async with db.pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM blog_articles WHERE slug = $1", slug)
    if not exists:
        raise HTTPException(status_code=404, detail="Article not found")

    ext = _Path(file.filename).suffix.lower() if file.filename else ".webp"
    if ext not in (".webp", ".png", ".jpg", ".jpeg"):
        raise HTTPException(status_code=400, detail="Only .webp, .png, .jpg allowed")

    filename = f"{slug}{ext}"
    dest = _BLOG_IMAGES_DIR / filename
    content = await file.read()
    dest.write_bytes(content)

    cover_url = f"/v1/blog/images/{filename}"
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE blog_articles SET cover_image = $1, updated_at = NOW() WHERE slug = $2",
            cover_url, slug,
        )
    _clear_blog_cache(slug)
    return {"status": "uploaded", "slug": slug, "cover_image": cover_url}


@router.patch("/admin/blog/articles/{slug}/publish", dependencies=[Depends(require_admin_token)])
async def admin_blog_toggle_publish(slug: str):
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE blog_articles
               SET published = NOT published, updated_at = NOW()
               WHERE slug = $1
               RETURNING slug, published""",
            slug,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Article not found")
    _clear_blog_cache(slug)
    if row["published"]:
        asyncio.create_task(_notify_indexnow([f"https://{SITE_HOST}/blog/{slug}"]))
    return {"slug": row["slug"], "published": row["published"]}
