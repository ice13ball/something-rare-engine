// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import type { ArticleListItem } from "../content/articles";

const SITE_URL = "https://something-rare.com";
const CANONICAL = `${SITE_URL}/blog`;
const API_BASE = import.meta.env.VITE_API_URL ?? "";

export function BlogListPage() {
  const [articles, setArticles] = useState<ArticleListItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${import.meta.env.VITE_API_URL ?? ""}/api/v1/blog/articles`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => { setArticles(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  return (
    <>
      <Helmet>
        <title>Blog | Abyssal Claims</title>
        <meta
          name="description"
          content="Articles on deep-sea mining, environmental monitoring, biodiversity, deforestation, and ocean-land policy — from the team behind Abyssal Claims."
        />
        <link rel="canonical" href={CANONICAL} />
        <meta property="og:title" content="Blog | Abyssal Claims" />
        <meta
          property="og:description"
          content="Articles on deep-sea mining, environmental monitoring, biodiversity, deforestation, and ocean-land policy."
        />
        <meta property="og:url" content={CANONICAL} />
        <meta property="og:type" content="website" />
        <meta property="og:image" content={`${SITE_URL}/og.jpg`} />
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content="Blog | Abyssal Claims" />
        <meta name="twitter:description" content="Articles on deep-sea mining, environmental monitoring, biodiversity, deforestation, and ocean-land policy." />
        <meta name="twitter:image" content={`${SITE_URL}/og.jpg`} />
      </Helmet>

      <div className="min-h-screen bg-[#0a0e14] text-white/90 font-sans">
        <div className="max-w-2xl mx-auto px-6 py-12">
          <Link to="/" className="text-white/80 hover:text-white/90 text-sm">
            ← Back to map
          </Link>

          <h1 className="text-2xl font-semibold mt-6 mb-2 text-white">
            Abyssal Claims Blog
          </h1>
          <p className="text-white/65 text-sm mb-10">
            Deep-sea mining, ocean governance, and the ecosystems at stake.
          </p>

          {loading ? (
            <ul className="space-y-6">
              {[0, 1, 2].map((i) => (
                <li key={i} className="bg-black/40 border border-white/10 rounded-xl p-5 animate-pulse">
                  <div className="h-3 bg-white/10 rounded w-32 mb-3" />
                  <div className="h-4 bg-white/10 rounded w-3/4 mb-2" />
                  <div className="h-3 bg-white/10 rounded w-full" />
                </li>
              ))}
            </ul>
          ) : (
            <ul className="space-y-6">
              {articles.map((article) => (
                <li key={article.slug}>
                  <Link
                    to={`/blog/${article.slug}`}
                    className="block bg-black/40 border border-white/10 rounded-xl overflow-hidden hover:border-white/20 hover:bg-black/60 transition-colors group"
                  >
                    {article.cover_image && (
                      <img
                        src={`${API_BASE}/api${article.cover_image}`}
                        alt={article.title}
                        width={400}
                        height={160}
                        className="w-full h-40 object-cover"
                        loading="lazy"
                      />
                    )}
                    <div className="p-5">
                    <div className="flex items-center gap-3 mb-2">
                      <time
                        dateTime={article.published_at}
                        className="text-white/60 text-xs font-mono"
                      >
                        {new Date(article.published_at).toLocaleDateString("en-GB", {
                          year: "numeric",
                          month: "long",
                          day: "numeric",
                        })}
                      </time>
                      <span className="text-white/50 text-xs">·</span>
                      <span className="text-white/60 text-xs">
                        {article.reading_time_min} min read
                      </span>
                    </div>

                    <h2 className="text-base font-semibold text-white group-hover:text-white transition-colors mb-1">
                      {article.title}
                    </h2>
                    <p className="text-white/70 text-sm leading-relaxed">
                      {article.description}
                    </p>

                    <div className="flex flex-wrap gap-1.5 mt-3">
                      {article.tags.map((tag) => (
                        <span
                          key={tag}
                          className="text-xs px-2 py-0.5 rounded-full bg-white/[0.06] text-white/70 border border-white/10"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </>
  );
}
