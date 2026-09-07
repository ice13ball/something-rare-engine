// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { ReportData } from "../ImpactReport";

interface Props {
  summary: ReportData["evidence_summary"];
  riskRating: string;
}

const ratingBorder: Record<string, string> = {
  Critical: "border-red-500/40",
  High: "border-orange-500/40",
  Moderate: "border-yellow-500/40",
  Low: "border-green-500/40",
};

const countCards: { key: string; color: string }[] = [
  { key: "Critical", color: "red" },
  { key: "High", color: "orange" },
  { key: "Moderate", color: "yellow" },
  { key: "Low", color: "green" },
];

export function EvidenceSummary({ summary, riskRating }: Props) {
  const border = ratingBorder[riskRating] ?? "border-white/10";

  return (
    <section id="evidence-summary" className="mb-8">
      <h2 className="text-xs text-white/55 uppercase tracking-widest mb-4 print:text-gray-500">
        6. Summary of Evidence
      </h2>

      <div className={`border ${border} rounded-xl p-5 bg-surface-scrim backdrop-blur-md print:bg-gray-50 print:border-gray-200`}>
        <p className="text-sm text-white/85 leading-relaxed mb-4 print:text-gray-700">
          {summary.narrative}
        </p>

        <div className="grid grid-cols-4 gap-3 mb-4">
          {countCards.map(card => (
            <div key={card.key} className="rounded-lg border px-3 py-2.5 text-center border-white/10 bg-black/30 print:bg-white print:border-gray-200">
              <div className={`text-lg font-mono font-bold text-${card.color}-400 print:text-gray-900`}>
                {summary.finding_counts[card.key] ?? 0}
              </div>
              <div className="text-[8px] text-white/60 uppercase print:text-gray-500">{card.key}</div>
            </div>
          ))}
        </div>

        <div className="border-t border-white/10 pt-3 print:border-gray-200">
          <h3 className="text-xs text-white/60 uppercase tracking-wider mb-2 print:text-gray-500">
            Recommended Actions
          </h3>
          <ul className="space-y-1">
            {summary.recommended_actions.map((action, i) => (
              <li key={i} className="text-[13px] text-white/80 flex gap-2 print:text-gray-600">
                <span className="text-white/50">&bull;</span> {action}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
