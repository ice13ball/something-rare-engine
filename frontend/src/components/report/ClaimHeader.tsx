// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { Link } from "react-router-dom";
import { exportPNG, exportPDF } from "../../utils/reportExport";

interface ClaimHeaderProps {
  isaId: string;
  contractorName: string;
  resourceType: string | null;
  areaKm2: number | null;
  actDate: string | null;
  expiryDate: string | null;
  jurisdiction: string | null;
  centroidLon: number | null;
  centroidLat: number | null;
  riskRating: string;
  generatedAt: string;
  reportRef: React.RefObject<HTMLDivElement | null>;
  onExportJSON?: () => void;
}

const resourceColor: Record<string, string> = {
  "Polymetallic Nodules": "amber",
  "Polymetallic Sulphides": "orange",
  "Cobalt-rich Ferromanganese Crusts": "blue",
};

const riskColor: Record<string, string> = {
  Critical: "red",
  High: "orange",
  Moderate: "yellow",
  Low: "green",
};

export function ClaimHeader({
  isaId,
  contractorName,
  resourceType,
  areaKm2,
  actDate,
  expiryDate,
  jurisdiction,
  centroidLon,
  centroidLat,
  riskRating,
  generatedAt,
  reportRef,
  onExportJSON,
}: ClaimHeaderProps) {
  const resColor = resourceColor[resourceType ?? ""] ?? "gray";
  const rColor = riskColor[riskRating] ?? "gray";

  return (
    <header className="mb-8">
      {/* Back link — fly to the claim centroid */}
      <Link
        to={centroidLon != null && centroidLat != null ? `/?fly=${centroidLon},${centroidLat},8` : "/"}
        className="inline-block text-white/80 hover:text-white/90 text-[13px] mb-4 print:hidden"
      >
        &larr; Back to map
      </Link>

      {/* Title */}
      <h1 className="text-xl font-semibold text-white/95 print:text-gray-900">
        Claim Impact Report
      </h1>

      {/* ISA ID */}
      <p className="text-lg font-bold text-white/90 mt-1 print:text-gray-800">
        {isaId}
      </p>

      {/* Contractor */}
      <p className="text-[13px] text-white/65 mt-0.5 print:text-gray-500">
        {contractorName}
      </p>

      {/* Badges */}
      <div className="flex flex-wrap items-center gap-2 mt-3">
        {/* Resource type badge */}
        {resourceType && (
          <span
            className={`inline-block px-3 py-1 rounded-full text-xs font-medium border bg-${resColor}-500/20 text-${resColor}-400 border-${resColor}-500/30 print:bg-white print:border-gray-300 print:text-gray-700`}
          >
            {resourceType}
          </span>
        )}

        {/* Risk rating badge */}
        <span
          className={`inline-block px-3 py-1 rounded-full text-xs font-medium border bg-${rColor}-500/20 text-${rColor}-400 border-${rColor}-500/30 print:bg-white print:border-gray-300 print:text-gray-700`}
        >
          {riskRating} Risk
        </span>
      </div>

      {/* Key stats grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-5">
        <div className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5 print:bg-white print:border-gray-200">
          <div className="text-xs text-white/60 uppercase print:text-gray-500">Area</div>
          <div className="text-sm font-semibold text-white/85 print:text-gray-900">
            {areaKm2 != null ? `${areaKm2.toLocaleString()} km\u00B2` : "\u2014"}
          </div>
        </div>
        <div className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5 print:bg-white print:border-gray-200">
          <div className="text-xs text-white/60 uppercase print:text-gray-500">Issued</div>
          <div className="text-sm font-semibold text-white/85 print:text-gray-900">
            {actDate ?? "\u2014"}
          </div>
        </div>
        <div className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5 print:bg-white print:border-gray-200">
          <div className="text-xs text-white/60 uppercase print:text-gray-500">Expires</div>
          <div className="text-sm font-semibold text-white/85 print:text-gray-900">
            {expiryDate ?? "\u2014"}
          </div>
        </div>
        <div className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5 print:bg-white print:border-gray-200">
          <div className="text-xs text-white/60 uppercase print:text-gray-500">Jurisdiction</div>
          <div className="text-sm font-semibold text-white/85 print:text-gray-900">
            {jurisdiction ?? "\u2014"}
          </div>
        </div>
      </div>

      {/* Centroid + timestamp */}
      <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-white/55 print:text-gray-400">
        {centroidLon != null && centroidLat != null && (
          <span>
            Centroid: {centroidLat.toFixed(3)}&deg;, {centroidLon.toFixed(3)}&deg;
          </span>
        )}
        <span>Generated {generatedAt}</span>
      </div>

      {/* Export buttons */}
      <div className="flex flex-wrap gap-2 mt-4 print:hidden">
        {[
          { label: "PDF", action: () => reportRef.current && exportPDF(reportRef.current, `claim-report-${isaId}.pdf`) },
          { label: "PNG", action: () => reportRef.current && exportPNG(reportRef.current, `claim-report-${isaId}.png`) },
          { label: "JSON", action: onExportJSON },
          { label: "Print", action: () => window.print() },
        ].map(btn => (
          <button
            key={btn.label}
            onClick={btn.action}
            className="px-3 py-1.5 text-xs rounded-md bg-white/5 hover:bg-white/10 text-white/80 hover:text-white/90 border border-white/10 transition-colors"
          >
            {btn.label}
          </button>
        ))}
      </div>
    </header>
  );
}
