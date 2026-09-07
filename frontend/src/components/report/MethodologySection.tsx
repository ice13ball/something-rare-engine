// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState } from "react";
import type { ReportData } from "../ImpactReport";

interface Props {
  methodology: ReportData["methodology"];
}

export function MethodologySection({ methodology }: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <section className="mb-8 bg-surface-scrim backdrop-blur-md border border-white/10 rounded-xl p-5 print:bg-gray-50 print:border-gray-200">
      {/* Header with collapse toggle */}
      <button
        onClick={() => setExpanded(prev => !prev)}
        className="w-full flex items-center justify-between text-left print:pointer-events-none"
      >
        <h2 className="text-[13px] font-semibold text-white/90 print:text-gray-900">
          2. Methodology &amp; Data Sources
        </h2>
        <span
          className={`text-white/60 text-[13px] transition-transform print:hidden ${expanded ? "rotate-180" : ""}`}
        >
          &#9660;
        </span>
      </button>

      {/* Collapsible body -- always visible in print */}
      <div className={`${expanded ? "block" : "hidden"} print:!block mt-4 space-y-4`}>
        {/* Depth-adaptive thresholds table */}
        <div>
          <h3 className="text-[13px] font-medium text-white/80 mb-2 print:text-gray-700">
            Depth-Adaptive Alarm Thresholds
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-white/70 print:text-gray-600">
              <thead>
                <tr className="border-b border-white/5 print:border-gray-200">
                  <th className="text-left py-1 pr-4">Parameter</th>
                  <th className="text-right py-1 px-2">Shallow (&lt;200m)</th>
                  <th className="text-right py-1 px-2">Mid (200-1000m)</th>
                  <th className="text-right py-1 px-2">Deep (&gt;1000m)</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-white/5 print:border-gray-100">
                  <td className="py-1 pr-4">Dissolved O2 (umol/kg)</td>
                  <td className="text-right px-2">&lt;150</td>
                  <td className="text-right px-2">&lt;90</td>
                  <td className="text-right px-2">&lt;60</td>
                </tr>
                <tr className="border-b border-white/5 print:border-gray-100">
                  <td className="py-1 pr-4">pH</td>
                  <td className="text-right px-2">&lt;7.95</td>
                  <td className="text-right px-2">&lt;7.75</td>
                  <td className="text-right px-2">&lt;7.60</td>
                </tr>
                <tr className="border-b border-white/5 print:border-gray-100">
                  <td className="py-1 pr-4">Temperature</td>
                  <td className="text-right px-2" colSpan={3}>&gt;2 sigma deviation from climatology</td>
                </tr>
                <tr>
                  <td className="py-1 pr-4">Salinity</td>
                  <td className="text-right px-2" colSpan={3}>&gt;2 sigma deviation from climatology</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* Scoring formula */}
        <div>
          <h3 className="text-[13px] font-medium text-white/80 mb-1 print:text-gray-700">
            Scoring Formula
          </h3>
          <p className="text-xs text-white/65 font-mono print:text-gray-600">
            {methodology.scoring_formula}
          </p>
        </div>

        {/* Plume backtrack details */}
        <div>
          <h3 className="text-[13px] font-medium text-white/80 mb-1 print:text-gray-700">
            Plume Backtracking
          </h3>
          <ul className="text-xs text-white/65 space-y-0.5 print:text-gray-600">
            <li>Hours backtracked: {methodology.plume_backtrack.hours}h</li>
            <li>Integration depth: {methodology.plume_backtrack.integration_depth_m}m</li>
            <li>Method: Lagrangian particle advection (reverse)</li>
            <li>Current source: {methodology.plume_backtrack.source}</li>
          </ul>
        </div>

        {/* Data sources */}
        <div>
          <h3 className="text-[13px] font-medium text-white/80 mb-1 print:text-gray-700">
            Data Sources
          </h3>
          <ul className="text-xs text-white/65 list-disc list-inside space-y-0.5 print:text-gray-600">
            {methodology.data_sources.map((src, i) => (
              <li key={i}>{src}</li>
            ))}
          </ul>
        </div>

        {/* Notes */}
        {methodology.notes && (
          <div>
            <h3 className="text-[13px] font-medium text-white/80 mb-1 print:text-gray-700">
              Notes
            </h3>
            <p className="text-xs text-white/65 leading-relaxed print:text-gray-600">
              {methodology.notes}
            </p>
          </div>
        )}
      </div>
    </section>
  );
}
