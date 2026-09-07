// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Helmet } from "react-helmet-async";
import { ClaimDossierV2 } from "./report/ClaimDossierV2";

const API = import.meta.env.VITE_API_BASE_URL || "";

type Attribution = { concession_id: string; distance_km: number };

type Measurement = {
  id: string;
  type: string;
  value: number;
  unit: string;
  baseline_p5: number;
  baseline_source: string;
  delta_from_baseline: number;
  observed_at: string;
  lat: number;
  lon: number;
  depth_m: number | null;
  attributed_to: Attribution[];
};

type PlumeBacktrack = {
  id: string;
  intersects_concession: string | null;
};

export type ClaimDossierV2Data = {
  claim: {
    concession_id: string;
    contractor_name: string;
    area_km2: number | null;
  };
  min_distance_km: number;
  attributed_measurement_count: number;
  attributed_plume_count: number;
  profiles_within_50km: number;
};

type NeutralReport = {
  platform_id: string;
  schema_version: "neutral-v1";
  generated_at: string;
  trail: {
    date_range_start: string;
    date_range_end: string;
    total_distance_km: number;
    profile_count: number;
  };
  summary: {
    measurements_below_baseline_p5: number;
    plume_backtracks_intersecting_concession: number;
    concessions_within_50km: number;
  };
  measurements: Measurement[];
  plume_backtracks: PlumeBacktrack[];
  claim_dossiers: ClaimDossierV2Data[];
  headline: string;
};

export function ImpactReportV2() {
  const { platformId } = useParams<{ platformId: string }>();
  const [data, setData] = useState<NeutralReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!platformId) return;
    let cancelled = false;

    async function load() {
      setLoading(true); setError(null); setData(null);
      try {
        // 1. Try cached
        const r0 = await fetch(`${API}/api/v2/reports/impact/${platformId}`);
        if (r0.ok) {
          if (cancelled) return;
          setData(await r0.json()); setLoading(false); return;
        }
        if (r0.status !== 404) {
          throw new Error(`v2 cache fetch failed: ${r0.status}`);
        }

        // 2. Kick off generation
        const r1 = await fetch(`${API}/api/v2/reports/impact`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ platform_id: platformId }),
        });
        if (!r1.ok) throw new Error(`v2 generation kickoff failed: ${r1.status}`);

        // 3. Poll status until ready
        const start = Date.now();
        const POLL_MS = 2000;
        const TIMEOUT_MS = 5 * 60_000;
        while (!cancelled) {
          if (Date.now() - start > TIMEOUT_MS) throw new Error("v2 generation timed out after 5 minutes");
          await new Promise(res => setTimeout(res, POLL_MS));
          const rs = await fetch(`${API}/api/v2/reports/impact/${platformId}/status`);
          if (!rs.ok) throw new Error(`v2 status fetch failed: ${rs.status}`);
          const sj = await rs.json();
          if (sj.status === "ready") {
            const rd = await fetch(`${API}/api/v2/reports/impact/${platformId}`);
            if (!rd.ok) throw new Error(`v2 cached fetch failed after ready: ${rd.status}`);
            if (cancelled) return;
            setData(await rd.json()); setLoading(false); return;
          }
          if (sj.status === "failed") throw new Error(sj.error || "v2 generation failed");
        }
      } catch (exc) {
        if (cancelled) return;
        setError(exc instanceof Error ? exc.message : String(exc));
        setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [platformId]);

  if (loading) {
    return <main className="min-h-screen bg-slate-950 text-white p-8">Generating report for {platformId}…</main>;
  }
  if (error) {
    return <main className="min-h-screen bg-slate-950 text-red-300 p-8">Error: {error}</main>;
  }
  if (!data) return null;

  return (
    <main className="min-h-screen bg-slate-950 text-white">
      {/*
        The canonical is /report/:platformId, NOT this URL.
        That is the address in sitemap-core.xml, the one with a server-rendered
        page behind it, and the one ReportRouter sent the visitor away from a
        moment ago. Without this tag the sitemap advertises 24 URLs that each
        JS-redirect to a page declaring no canonical at all, so Google has to
        guess which of the pair is the page — and neither of them says.
      */}
      <Helmet>
        <title>{data.headline}</title>
        <meta name="description" content={data.headline} />
        <link rel="canonical" href={`https://something-rare.com/report/${encodeURIComponent(String(data.platform_id))}`} />
      </Helmet>

      <header className="max-w-3xl mx-auto p-8 border-b border-white/10">
        <h1 className="text-2xl font-semibold">Argo float {data.platform_id}</h1>
        <p className="mt-2 text-white/85">
          <span className="font-mono">{data.trail.total_distance_km}</span> km drift{" · "}
          {data.trail.date_range_start} → {data.trail.date_range_end}{" · "}
          <span className="font-mono">{data.trail.profile_count}</span> profiles
        </p>
      </header>

      <section className="max-w-3xl mx-auto p-8 border-b border-white/10">
        <h2 className="text-xs uppercase tracking-wider text-white/70">Summary</h2>
        <ul className="mt-3 space-y-1 text-white/90">
          <li>
            <span className="font-mono">{data.summary.measurements_below_baseline_p5}</span>{" "}
            measurements below dataset 5th-percentile baseline
          </li>
          <li>
            <span className="font-mono">{data.summary.plume_backtracks_intersecting_concession}</span>{" "}
            plume backtracks intersect a concession boundary
          </li>
          <li>
            <span className="font-mono">{data.summary.concessions_within_50km}</span>{" "}
            concessions within 50 km of the float trail
          </li>
        </ul>
      </section>

      <section className="max-w-3xl mx-auto p-8 border-b border-white/10">
        <h2 className="text-xs uppercase tracking-wider text-white/70">
          Concessions (nearest first)
        </h2>
        <div className="mt-4 space-y-4">
          {data.claim_dossiers.length === 0 && (
            <p className="text-white/70">No concessions within the analysed area.</p>
          )}
          {data.claim_dossiers.map(d => (
            <ClaimDossierV2 key={d.claim.concession_id} dossier={d} />
          ))}
        </div>
      </section>

      <section className="max-w-3xl mx-auto p-8">
        <h2 className="text-xs uppercase tracking-wider text-white/70">
          Measurements (chronological)
        </h2>
        <ul className="mt-4 space-y-3">
          {data.measurements.length === 0 && (
            <li className="text-white/70">No measurements below the baseline.</li>
          )}
          {data.measurements.map(m => (
            <li key={m.id} className="border-l-2 border-white/10 pl-3">
              <div className="text-white/80 text-xs">
                {new Date(m.observed_at).toISOString().replace("T", " ").slice(0, 16)} UTC · {m.type}
              </div>
              <div className="font-mono">
                value {m.value} {m.unit} · baseline_p5 {m.baseline_p5} (Δ {m.delta_from_baseline})
              </div>
              <div className="text-white/80 text-xs">
                {m.depth_m != null && <>{m.depth_m} m depth · </>}
                {m.attributed_to.length > 0 ? (
                  <>attributed to{" "}
                    {m.attributed_to.map(a => (
                      <span key={a.concession_id}>
                        <span className="font-semibold">{a.concession_id}</span> ({a.distance_km} km)
                      </span>
                    ))}
                  </>
                ) : "unattributed"}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <footer className="max-w-3xl mx-auto p-8 text-xs text-white/65">
        Generated {new Date(data.generated_at).toISOString().slice(0, 19).replace("T", " ")} UTC ·
        schema {data.schema_version}
      </footer>
    </main>
  );
}
