// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useMapStore } from "../store/mapStore";

const API = import.meta.env.VITE_API_BASE_URL ?? "";
const POLL_INTERVAL = 4000;

export function ReportToast() {
  const jobs = useMapStore((s) => s.reportJobs);
  const updateJob = useMapStore((s) => s.updateReportJob);
  const dismissJob = useMapStore((s) => s.dismissReportJob);
  const navigate = useNavigate();
  const timers = useRef<Record<string, number>>({});

  // Poll status for all "generating" jobs
  useEffect(() => {
    const generating = jobs.filter((j) => j.status === "generating");

    for (const job of generating) {
      if (timers.current[job.platformId]) continue; // already polling

      const poll = () => {
        const statusUrl = job.type === "claim"
          ? `${API}/api/v1/reports/claim-impact/${job.platformId}/status`
          : job.type === "chess"
          ? `${API}/api/v1/reports/chess-site/${encodeURIComponent(job.platformId)}/status`
          : `${API}/api/v1/reports/impact/${job.platformId}/status`;
        fetch(statusUrl)
          .then((r) => r.json())
          .then((d) => {
            if (d.status === "ready") {
              updateJob(job.platformId, "ready");
              clearInterval(timers.current[job.platformId]);
              delete timers.current[job.platformId];
            } else if (d.status === "failed") {
              updateJob(job.platformId, "failed", d.error);
              clearInterval(timers.current[job.platformId]);
              delete timers.current[job.platformId];
            }
          })
          .catch(() => {}); // silent — will retry next interval
      };

      timers.current[job.platformId] = window.setInterval(poll, POLL_INTERVAL);
      // First poll after a short delay (report might be cached)
      window.setTimeout(poll, 1500);
    }

    // Clean up timers for jobs no longer generating
    for (const pid of Object.keys(timers.current)) {
      if (!generating.some((j) => j.platformId === pid)) {
        clearInterval(timers.current[pid]);
        delete timers.current[pid];
      }
    }

    return () => {
      for (const t of Object.values(timers.current)) clearInterval(t);
    };
  }, [jobs, updateJob]);

  if (jobs.length === 0) return null;

  return (
    <div aria-live="assertive" className="fixed bottom-4 left-4 z-toast flex flex-col gap-2 pointer-events-auto max-w-[320px]">
      {jobs.map((job) => (
        <div
          key={job.platformId}
          className={`flex items-center gap-3 px-4 py-3 rounded-xl border shadow-lg text-[13px] ${
            job.status === "generating"
              ? "bg-surface-overlay border-white/20 text-white/85"
              : job.status === "ready"
              ? "bg-surface-overlay border-emerald-500/30 text-emerald-300"
              : "bg-surface-overlay border-red-500/30 text-red-300"
          }`}
        >
          {job.status === "generating" && (
            <>
              <div className="w-4 h-4 border-2 border-white/30 border-t-white/70 rounded-full animate-spin flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="font-medium truncate">{job.type === "claim" ? "Claim" : job.type === "chess" ? "Site" : "Float"} {job.platformId}</p>
                <p className="text-xs text-white/60">Generating report...</p>
              </div>
            </>
          )}

          {job.status === "ready" && (
            <>
              <svg aria-hidden="true" className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
              <div className="flex-1 min-w-0">
                <p className="font-medium truncate">{job.type === "claim" ? "Claim" : job.type === "chess" ? "Site" : "Float"} {job.platformId}</p>
                <p className="text-xs text-white/60">Report ready</p>
              </div>
              <button
                onClick={() => {
                  dismissJob(job.platformId);
                  navigate(
                    job.type === "claim" ? `/claim-report/${job.platformId}`
                    : job.type === "chess" ? `/chess-report/${encodeURIComponent(job.platformId)}`
                    : `/report/${job.platformId}`
                  );
                }}
                className="px-2 py-1 rounded bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 text-xs font-medium flex-shrink-0"
              >
                View
              </button>
            </>
          )}

          {job.status === "failed" && (
            <>
              <svg aria-hidden="true" className="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
              <div className="flex-1 min-w-0">
                <p className="font-medium truncate">{job.type === "claim" ? "Claim" : job.type === "chess" ? "Site" : "Float"} {job.platformId}</p>
                <p className="text-[10px] font-mono text-white/60 truncate" title={job.error}>
                  {job.error || "Generation failed"}
                </p>
              </div>
              <button
                onClick={() => {
                  dismissJob(job.platformId);
                  // Re-trigger via store — the panel button will be available again
                  useMapStore.getState().updateReportJob(job.platformId, "generating");
                  const url = job.type === "claim"
                    ? `${API}/api/v1/reports/claim-impact`
                    : job.type === "chess"
                    ? `${API}/api/v1/reports/chess-site`
                    : `${API}/api/v1/reports/impact`;
                  const body = job.type === "claim"
                    ? { isa_id: job.platformId }
                    : job.type === "chess"
                    ? { locality: job.platformId }
                    : { platform_id: job.platformId };
                  useMapStore.getState().startReportJob(job.platformId, job.type);
                  const ctrl = new AbortController();
                  setTimeout(() => ctrl.abort(), 120_000);
                  fetch(url, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(body),
                    signal: ctrl.signal,
                  }).then(r => {
                    if (!r.ok) useMapStore.getState().updateReportJob(job.platformId, "failed", `Server ${r.status}`);
                  }).catch(e => {
                    const msg = e?.name === "AbortError" ? "Timed out (120s)" : "Network error";
                    useMapStore.getState().updateReportJob(job.platformId, "failed", msg);
                  });
                }}
                className="px-2 py-1 rounded bg-red-500/15 text-red-300/80 hover:bg-red-500/25 text-xs font-mono flex-shrink-0 transition-colors"
              >
                Retry
              </button>
            </>
          )}

          <button
            onClick={() => dismissJob(job.platformId)}
            className="text-white/65 hover:text-white/80 text-[14px] leading-none flex-shrink-0"
          >
            &times;
          </button>
        </div>
      ))}
    </div>
  );
}
