// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Helmet } from "react-helmet-async";

interface SeoData {
  meta: { title: string; description: string; canonical_url: string; json_ld: object };
  [key: string]: unknown;
}

const API = import.meta.env.VITE_API_BASE_URL ?? "";


export function SeoPage({ type }: { type: "concession" | "vent" | "seamount" }) {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<SeoData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`${API}/api/v1/seo/${type}/${id}`)
      .then(r => r.ok ? r.json() : null)
      .then(setData)
      .finally(() => setLoading(false));
  }, [type, id]);

  if (loading) return (
    <div className="min-h-screen bg-[#0a0e14] flex items-center justify-center">
      <p className="text-white/60 animate-pulse">Loading…</p>
    </div>
  );

  if (!data) return (
    <div className="min-h-screen bg-[#0a0e14] flex flex-col items-center justify-center gap-4">
      <p className="text-white/70">Not found.</p>
      <Link to="/" className="text-white/80 hover:text-white/90 text-sm">← Back to map</Link>
    </div>
  );

  const m = data.meta;
  // Prefer the ?focus= deep-link over bare ?fly= coordinates: focus activates
  // the feature's layer, waits for its data, flies to it AND opens its panel —
  // so the visitor lands on the actual object, not an empty stretch of ocean.
  // Vents are matched by name in the focus handler; seamounts by peak_id;
  // concessions resolve via searchById (isa_id).
  const focusParam =
    type === "vent" && data.name ? `vent:${String(data.name)}` :
    type === "seamount" && id    ? `seamount:${id}` :
    type === "concession" && id  ? String(id) :
    null;
  const flyLon = Number(data.longitude ?? data.centroid_lon ?? data.lon);
  const flyLat = Number(data.latitude ?? data.centroid_lat ?? data.lat);
  const backUrl = focusParam
    ? `/?focus=${encodeURIComponent(focusParam)}`
    : !isNaN(flyLon) && !isNaN(flyLat) ? `/?fly=${flyLon},${flyLat},10` : "/";
  return (
    <>
      <Helmet>
        <title>{m.title}</title>
        <meta name="description" content={m.description} />
        <link rel="canonical" href={m.canonical_url} />
        <meta property="og:title" content={m.title} />
        <meta property="og:description" content={m.description} />
        <meta property="og:url" content={m.canonical_url} />
        <script type="application/ld+json">{JSON.stringify(m.json_ld)}</script>
      </Helmet>
      <div className="min-h-screen bg-[#0a0e14] text-white/90 p-6 max-w-2xl mx-auto font-sans">
        <Link to={backUrl} className="text-white/80 hover:text-white/90 text-sm">← Back to map</Link>
        <h1 className="text-xl font-semibold mt-4 mb-2">{m.title.split(' | ')[0]}</h1>
        <p className="text-white/65 text-sm mb-6">{m.description}</p>

        <div className="bg-surface-scrim backdrop-blur-md border border-white/10 rounded-xl p-4 mb-4">
          {Object.entries(data)
            .filter(([k]) => k !== 'meta')
            .map(([k, v]) => (
              v != null && (
                <div key={k} className="flex justify-between py-1.5 border-b border-white/5 last:border-0">
                  <span className="text-white/65 text-xs">{k.replace(/_/g, ' ')}</span>
                  <span className="text-white/85 text-xs font-mono text-right">
                    {typeof v === 'boolean' ? (v ? 'Yes' : 'No') :
                     Array.isArray(v) ? v.join(', ') || '—' :
                     String(v)}
                  </span>
                </div>
              )
            ))}
        </div>

        <Link to={backUrl}
          className="inline-block py-2 px-4 text-sm rounded-lg bg-white/10 border border-white/20 text-white/90 hover:bg-white/15 transition-colors">
          View on interactive 3D map →
        </Link>
      </div>
    </>
  );
}
