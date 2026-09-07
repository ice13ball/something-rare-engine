// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { Link } from "react-router-dom";
import { exportPNG, exportPDF, exportCSV } from "../../utils/reportExport";
import type { ReportData } from "../ImpactReport";

interface Props {
  data: ReportData;
  reportRef: React.RefObject<HTMLDivElement | null>;
}

const ratingColor: Record<string, string> = {
  Critical: "red",
  High: "orange",
  Moderate: "yellow",
  Low: "green",
};

export function ReportHeader({ data, reportRef }: Props) {
  const color = ratingColor[data.executive_summary.risk_rating] ?? "gray";
  const rating = data.executive_summary.risk_rating;
  const dateRange = data.trail.date_range;

  const handlePNG = async () => {
    if (!reportRef.current) return;
    await exportPNG(reportRef.current, `impact-report-${data.platform_id}.png`);
  };

  const handlePDF = async () => {
    if (!reportRef.current) return;
    await exportPDF(reportRef.current, `impact-report-${data.platform_id}.pdf`);
  };

  const handleCSV = () => {
    const rows = Object.entries(data.sensor_timelines).flatMap(([type, points]) =>
      points.map(p => ({
        type,
        date: p.date,
        value: p.value,
        claim_distance_km: p.claim_distance_km,
        threshold: p.threshold,
        alarmed: p.alarmed,
      })),
    );
    exportCSV(rows, `sensor-data-${data.platform_id}.csv`);
  };

  const handleJSON = () => {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.download = `impact-report-${data.platform_id}.json`;
    link.href = URL.createObjectURL(blob);
    link.click();
    URL.revokeObjectURL(link.href);
  };

  return (
    <header className="mb-8">
      {/* Back link — fly to the float's last known position */}
      <Link
        to={(() => {
          const p = data.trail.profiles[data.trail.profiles.length - 1];
          return p ? `/?fly=${p.lon},${p.lat},9` : "/";
        })()}
        className="inline-block text-white/80 hover:text-white/90 text-[13px] mb-4 print:hidden"
      >
        &larr; Back to map
      </Link>

      {/* Title */}
      <h1 className="text-xl font-semibold text-white/95 print:text-gray-900">
        Environmental Impact Evidence Report
      </h1>

      {/* Subtitle */}
      <p className="text-[13px] text-white/65 mt-1 print:text-gray-500">
        Platform {data.platform_id} &middot; {dateRange.start} &ndash; {dateRange.end}
      </p>

      {/* Risk rating badge */}
      <span
        className={`inline-block mt-3 px-3 py-1 rounded-full text-xs font-medium border bg-${color}-500/20 text-${color}-400 border-${color}-500/30 print:bg-white print:border-gray-300 print:text-gray-700`}
      >
        {rating} Risk
      </span>

      {/* Export buttons */}
      <div className="flex flex-wrap gap-2 mt-4 print:hidden">
        {[
          { label: "PNG", action: handlePNG },
          { label: "PDF", action: handlePDF },
          { label: "CSV", action: handleCSV },
          { label: "JSON", action: handleJSON },
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
