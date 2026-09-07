// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useRef, useState } from "react";
import { Helmet } from "react-helmet-async";
import { Link, useParams } from "react-router-dom";
import { ConcessionDossierV2, type ConcessionV2Data } from "./report/ConcessionDossierV2";

const TIMEOUT_MS  = 5 * 60_000;
const POLL_MS     = 3_000;

type ApiState =
  | { kind: "loading" }
  | { kind: "ready"; data: ConcessionV2Data }
  | { kind: "error"; message: string };

export function ImpactReportV2Concession() {
  const { isaId } = useParams<{ isaId: string }>();
  const [state, setState] = useState<ApiState>({ kind: "loading" });
  const cancelledRef = useRef(false);

  useEffect(() => {
    cancelledRef.current = false;
    if (!isaId) {
      setState({ kind: "error", message: "Missing concession ID" });
      return () => { cancelledRef.current = true; };
    }

    const startedAt = Date.now();

    async function tryFetch(): Promise<ConcessionV2Data | null> {
      const r = await fetch(`/api/v2/reports/concession/${encodeURIComponent(isaId!)}`);
      if (r.status === 200) return r.json();
      return null;
    }

    async function startGeneration(): Promise<void> {
      await fetch(`/api/v2/reports/concession`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ isa_id: isaId }),
      });
    }

    async function poll(): Promise<void> {
      while (!cancelledRef.current) {
        if (Date.now() - startedAt > TIMEOUT_MS) {
          setState({ kind: "error", message: "Report generation timed out after 5 minutes." });
          return;
        }
        const data = await tryFetch();
        if (cancelledRef.current) return;
        if (data) {
          setState({ kind: "ready", data });
          return;
        }
        await new Promise((res) => setTimeout(res, POLL_MS));
      }
    }

    (async () => {
      const initial = await tryFetch();
      if (cancelledRef.current) return;
      if (initial) {
        setState({ kind: "ready", data: initial });
        return;
      }
      await startGeneration();
      if (cancelledRef.current) return;
      await poll();
    })().catch((e) => {
      if (!cancelledRef.current) setState({ kind: "error", message: String(e?.message ?? e) });
    });

    return () => { cancelledRef.current = true; };
  }, [isaId]);

  return (
    <main className="min-h-screen bg-[#0a0e14] text-white/90 font-sans">
      {/*
        This component had NO <Helmet> at all, so a crawler arriving here after
        ClaimReportRedirect / ReportRouter navigated it away from the sitemap'd
        URL found a page with the home page's title, the home page's description
        and no canonical. The canonical below points back at /claim-report/:isaId
        — the address in sitemap-core.xml with a server-rendered page behind it.
      */}
      <Helmet>
        <title>{isaId ? `Claim Impact Report — ${isaId}` : "Claim Impact Report"} · Abyssal Claims</title>
        <meta
          name="description"
          content={`Neutral measurement report for ISA concession ${isaId ?? ""}: observed environmental measurements near the claim area, without risk scoring.`}
        />
        {isaId && (
          <link rel="canonical" href={`https://something-rare.com/claim-report/${encodeURIComponent(isaId)}`} />
        )}
      </Helmet>
      <div className="max-w-5xl mx-auto p-6">
        <Link to="/" className="text-white/70 hover:text-white/90 text-sm">← Back to map</Link>
        <h1 className="mt-3 mb-1 text-2xl font-semibold text-white">Claim Impact Report</h1>
        <p className="text-white/65 text-sm mb-6">Neutral measurement view.</p>

        {state.kind === "loading" && (
          <div className="rounded-lg border border-white/10 bg-white/5 p-8 text-white/80">
            Loading or generating report for <span className="font-mono">{isaId}</span>…
          </div>
        )}
        {state.kind === "error" && (
          <div className="rounded-lg border border-rose-500/30 bg-rose-950/30 p-6 text-rose-200">
            {state.message}
          </div>
        )}
        {state.kind === "ready" && <ConcessionDossierV2 data={state.data} />}
      </div>
    </main>
  );
}
