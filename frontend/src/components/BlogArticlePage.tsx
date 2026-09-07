// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";
import { useParams, Link, Navigate } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import type { ArticleFull } from "../content/articles";
import { MarkdownRenderer } from "../utils/renderMarkdown";

const SITE_URL = "https://something-rare.com";

export function BlogArticlePage() {
  const { slug } = useParams<{ slug: string }>();
  const [article, setArticle] = useState<ArticleFull | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!slug) return;
    setLoading(true);
    setNotFound(false);
    fetch(`${import.meta.env.VITE_API_URL ?? ""}/api/v1/blog/articles/${slug}`)
      .then((r) => {
        if (!r.ok) { setNotFound(true); return null; }
        return r.json();
      })
      .then((data) => { if (data) setArticle(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [slug]);

  if (notFound) return <Navigate to="/blog" replace />;

  if (loading) {
    return (
      <div className="min-h-screen bg-[#0a0e14] text-white/90 font-sans">
        <div className="max-w-2xl mx-auto px-6 py-12 animate-pulse">
          <div className="h-3 bg-white/10 rounded w-24 mb-8" />
          <div className="h-6 bg-white/10 rounded w-3/4 mb-4" />
          <div className="space-y-3">
            {[1, 2, 3, 4].map((i) => <div key={i} className="h-3 bg-white/10 rounded" />)}
          </div>
        </div>
      </div>
    );
  }

  if (!article) return null;

  const canonicalUrl = `${SITE_URL}/blog/${article.slug}`;
  const apiBase = import.meta.env.VITE_API_URL ?? "";
  const ogImage = article.cover_image
    ? `${SITE_URL}/api${article.cover_image}`
    : `${SITE_URL}/og.jpg`;
  const jsonLd = JSON.stringify({
    "@context": "https://schema.org",
    "@type": "Article",
    headline: article.title,
    description: article.description,
    url: canonicalUrl,
    datePublished: article.published_at,
    dateModified: article.published_at,
    image: ogImage,
    author: { "@type": "Organization", name: "Abyssal Claims", url: SITE_URL },
    publisher: { "@type": "Organization", name: "Abyssal Claims", url: SITE_URL },
    keywords: article.tags.join(", "),
    inLanguage: "en",
  });

  return (
    <>
      <Helmet>
        <title>{article.title} | Abyssal Claims</title>
        <meta name="description" content={article.description} />
        <link rel="canonical" href={canonicalUrl} />
        <meta property="og:title" content={`${article.title} | Abyssal Claims`} />
        <meta property="og:description" content={article.description} />
        <meta property="og:url" content={canonicalUrl} />
        <meta property="og:type" content="article" />
        <meta property="article:published_time" content={article.published_at} />
        <meta property="og:image" content={ogImage} />
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content={`${article.title} | Abyssal Claims`} />
        <meta name="twitter:description" content={article.description} />
        <meta name="twitter:image" content={ogImage} />
        <script type="application/ld+json">{jsonLd}</script>
        {article.ai_generated && (
          <meta name="ai-generated" content="true" />
        )}
      </Helmet>

      <div className="min-h-screen bg-[#0a0e14] text-white/90 font-sans">
        <div className="max-w-2xl mx-auto px-6 py-12">
          <Link to="/blog" className="text-white/80 hover:text-white/90 text-sm">
            ← All articles
          </Link>

          <div className="flex items-center gap-3 mt-6 mb-3">
            <time dateTime={article.published_at} className="text-white/60 text-xs font-mono">
              {new Date(article.published_at).toLocaleDateString("en-GB", {
                year: "numeric",
                month: "long",
                day: "numeric",
              })}
            </time>
            <span className="text-white/50 text-xs">·</span>
            <span className="text-white/60 text-xs">{article.reading_time_min} min read</span>
          </div>

          <h1 className="text-2xl font-semibold text-white mb-4">{article.title}</h1>

          <div className="flex flex-wrap gap-1.5 mb-8">
            {article.tags.map((tag) => (
              <span
                key={tag}
                className="text-xs px-2 py-0.5 rounded-full bg-white/[0.06] text-white/70 border border-white/10"
              >
                {tag}
              </span>
            ))}
            {article.ai_generated && (
              <span
                title="This article was drafted with the assistance of an AI language model and reviewed for factual accuracy. EU AI Act Article 50 disclosure."
                className="text-xs px-2 py-0.5 rounded-full bg-slate-500/10 text-slate-400/70 border border-slate-500/20 cursor-help"
              >
                AI-assisted
              </span>
            )}
          </div>

          {article.cover_image && (
            <div className="mb-8 rounded-xl overflow-hidden border border-white/10">
              <img
                src={`${apiBase}/api${article.cover_image}`}
                alt={article.title}
                width={800}
                height={450}
                className="w-full h-auto object-cover"
                loading="eager"
              />
            </div>
          )}

          <MarkdownRenderer markdown={article.content_md} />

          <div className="mt-12 pt-6 border-t border-white/10 flex flex-col sm:flex-row items-start sm:items-center gap-3">
            <Link
              to="/"
              className="inline-block py-2.5 px-5 text-sm rounded-lg bg-white/10 border border-white/20 text-white/90 hover:bg-white/15 hover:border-white/30 transition-colors font-medium"
            >
              Explore the interactive map →
            </Link>
            <Link
              to="/blog"
              className="inline-block py-2.5 px-5 text-sm rounded-lg border border-white/10 text-white/65 hover:text-white/85 hover:border-white/20 transition-colors"
            >
              ← All articles
            </Link>
          </div>
        </div>
      </div>
    </>
  );
}
