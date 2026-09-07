// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Article type definitions for the DB-backed blog API.
// Articles are served from /api/v1/blog/articles — see backend/main.py.

export interface ArticleListItem {
  slug: string;
  title: string;
  description: string;
  tags: string[];
  reading_time_min: number;
  published_at: string;
  ai_generated?: boolean;
  cover_image?: string | null;
}

export interface ArticleFull extends ArticleListItem {
  content_md: string;
}
