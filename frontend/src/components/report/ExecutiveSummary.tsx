// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { ReportData } from "../ImpactReport";

export interface StatCard {
  key: string;
  label: string;
  color: string;
  format?: (v: number | string) => string;
}

interface Props {
  summary: ReportData["executive_summary"];
  statCards?: StatCard[];
}

const DEFAULT_STAT_CARDS: StatCard[] = [
  { key: "alarm_count", label: "Alarms", color: "red" },
  { key: "claims_implicated", label: "Claims Implicated", color: "amber" },
  { key: "endangered_species_count", label: "Threatened Species (IUCN)", color: "amber" },
  { key: "total_distance_km", label: "km Drift", color: "cyan", format: (v) => typeof v === "number" ? v.toFixed(0) : String(v) },
];

export function ExecutiveSummary({ summary, statCards }: Props) {
  const cards = statCards ?? DEFAULT_STAT_CARDS;
  return (
    <section className="mb-8 bg-surface-scrim backdrop-blur-md border border-white/10 rounded-xl p-5 print:bg-gray-50 print:border-gray-200">
      <h2 className="text-[13px] font-semibold text-white/90 mb-4 print:text-gray-900">
        1. Executive Summary
      </h2>

      {/* Stats grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        {cards.map(card => {
          const raw = summary.key_stats[card.key];
          const value = raw != null ? (card.format ? card.format(raw) : raw) : "--";
          return (
            <div
              key={card.key}
              className={`rounded-lg border px-3 py-2.5 text-center bg-${card.color}-500/10 border-${card.color}-500/20 print:bg-white print:border-gray-200`}
            >
              <div className={`text-lg font-bold text-${card.color}-400 print:text-gray-900`}>
                {value}
              </div>
              <div className="text-xs text-white/65 print:text-gray-500">{card.label}</div>
            </div>
          );
        })}
      </div>

      {/* Narrative */}
      <div className="border-t border-white/5 pt-3 print:border-gray-200">
        <p className="text-[13px] text-white/80 leading-relaxed print:text-gray-700">
          {summary.narrative}
        </p>
      </div>
    </section>
  );
}
