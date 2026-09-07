// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { Navigate, useParams } from "react-router-dom";

/**
 * Default /report/:id entry point. Dispatches to the neutral v2 report
 * matching the ID shape:
 *   - all-digits  → Argo platform report  (/report/v2/argo/:platformId)
 *   - otherwise   → ISA concession report (/report/v2/concession/:isaId)
 *
 * v1 (risk-scored) reports stay reachable at /report/v1/:platformId as the
 * frozen restore path. To roll back to v1 as the default, point /report/:id
 * back at <ImpactReport/> in App.tsx — one-line swap, v1 cache stays warm.
 */
export function ReportRouter() {
  const { platformId } = useParams<{ platformId: string }>();
  if (!platformId) return <Navigate to="/" replace />;

  // ⚠️ `report_cache` holds THREE kinds of report under one primary key, not
  // two. `chess:<locality>` is a ChESS vent-locality report and has its own
  // component and its own API; the all-digits test sent it down the `else`
  // branch to the concession report, whose endpoint answers **404** for it
  // (verified live 2026-08-18: /v2/reports/concession/chess%3ATAG → 404, while
  // /v1/reports/chess-site/TAG → 200). Bots never saw it because they get the
  // SSR page at /report/chess:TAG instead — so the break was human-only.
  if (platformId.startsWith("chess:")) {
    const locality = platformId.slice("chess:".length);
    return <Navigate to={`/chess-report/${encodeURIComponent(locality)}`} replace />;
  }

  const isArgoPlatform = /^\d+$/.test(platformId);
  const target = isArgoPlatform
    ? `/report/v2/argo/${encodeURIComponent(platformId)}`
    : `/report/v2/concession/${encodeURIComponent(platformId)}`;

  return <Navigate to={target} replace />;
}

/**
 * Default /claim-report/:isaId entry point. The map's "View report" action
 * (ReportToast, job.type === "claim") navigates here, so this is the live
 * concession-report path. Always a concession → redirect to the neutral v2
 * concession report. v1 ClaimReport stays reachable at /claim-report/v1/:isaId.
 */
export function ClaimReportRedirect() {
  const { isaId } = useParams<{ isaId: string }>();
  if (!isaId) return <Navigate to="/" replace />;
  return <Navigate to={`/report/v2/concession/${encodeURIComponent(isaId)}`} replace />;
}
