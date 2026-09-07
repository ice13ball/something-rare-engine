// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState } from "react";
import type { AlarmEntry } from "../ImpactReport";

interface Props {
  alarms: AlarmEntry[];
}

const ALARM_LABELS: Record<string, string> = {
  low_oxygen: "Low O\u2082",
  low_ph: "Low pH",
};

const SEVERITY_COLOR: Record<string, string> = {
  Critical: "text-red-400",
  High: "text-orange-400",
  Moderate: "text-yellow-400",
  Low: "text-green-400",
};

export function AlarmLog({ alarms }: Props) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? alarms : alarms.slice(0, 10);

  if (alarms.length === 0) {
    return (
      <p className="text-white/50 text-[13px] italic">No alarm events recorded.</p>
    );
  }

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="text-white/60 border-b border-white/5">
              <th className="py-1 px-2 text-left font-medium">#</th>
              <th className="py-1 px-2 text-left font-medium">Date</th>
              <th className="py-1 px-2 text-left font-medium">Type</th>
              <th className="py-1 px-2 text-right font-medium">Value</th>
              <th className="py-1 px-2 text-right font-medium">Threshold</th>
              <th className="py-1 px-2 text-right font-medium">Severity</th>
              <th className="py-1 px-2 text-left font-medium">Nearest Claim</th>
              <th className="py-1 px-2 text-right font-medium">Distance</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((a, i) => (
              <tr key={a.alarm_id} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                <td className="py-1 px-2 text-white/50">{i + 1}</td>
                <td className="py-1 px-2 text-white/70">{a.date.slice(0, 10)}</td>
                <td className="py-1 px-2 text-white/80">{ALARM_LABELS[a.type] ?? a.type}</td>
                <td className="py-1 px-2 text-right text-white/70">{a.value?.toFixed(2) ?? "—"}</td>
                <td className="py-1 px-2 text-right text-white/60">{a.threshold?.toFixed(2) ?? "—"}</td>
                <td className={`py-1 px-2 text-right font-medium ${SEVERITY_COLOR[a.severity] ?? "text-white/65"}`}>
                  {a.severity}
                </td>
                <td className="py-1 px-2">
                  <span className="max-w-[120px] truncate block text-white/65">
                    {a.nearest_claim_name ?? "—"}
                  </span>
                </td>
                <td className="py-1 px-2 text-right text-white/60">
                  {a.distance_km != null ? `${a.distance_km.toFixed(0)} km` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {alarms.length > 10 && (
        <button
          onClick={() => setExpanded(e => !e)}
          className="mt-2 text-xs text-white/70 hover:text-white/90 transition-colors"
        >
          {expanded ? "Show fewer" : `Show all ${alarms.length} alarms`}
        </button>
      )}
    </div>
  );
}
