# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""Schema DDL — blog domain. Extracted verbatim from the former backend/schema.py.
"""
from __future__ import annotations

from domains.blog import seed_blog_if_empty


async def ensure_blog(conn) -> None:
    """blog_articles."""

    await conn.execute("""
        CREATE TABLE IF NOT EXISTS blog_articles (
            id               SERIAL PRIMARY KEY,
            slug             TEXT UNIQUE NOT NULL,
            title            TEXT NOT NULL,
            description      TEXT NOT NULL,
            content_md       TEXT NOT NULL,
            tags             TEXT[] DEFAULT '{}',
            reading_time_min INTEGER DEFAULT 5,
            published        BOOLEAN DEFAULT FALSE,
            published_at     DATE,
            ai_generated     BOOLEAN DEFAULT FALSE,
            created_at       TIMESTAMPTZ DEFAULT NOW(),
            updated_at       TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS blog_articles_slug_idx
            ON blog_articles (slug);
        CREATE INDEX IF NOT EXISTS blog_articles_published_idx
            ON blog_articles (published, published_at DESC);
    """)
    await conn.execute("ALTER TABLE blog_articles OWNER TO abyssal_user")
    # Migration: add ai_generated column if it doesn't exist yet
    await conn.execute("""
        ALTER TABLE blog_articles
        ADD COLUMN IF NOT EXISTS ai_generated BOOLEAN DEFAULT FALSE
    """)
    # Migration: add cover_image column for blog article hero images
    await conn.execute("""
        ALTER TABLE blog_articles
        ADD COLUMN IF NOT EXISTS cover_image TEXT
    """)

    await seed_blog_if_empty(conn)


