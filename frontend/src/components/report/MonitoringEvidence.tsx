// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

interface MonitoringEvidenceProps {
  uniqueFloats: string[];
  profiles: Array<{
    platform_id: string;
    distance_to_claim_km: number;
    alarms: string[];
  }>;
  alarmCount: number;
  dateRange: { start: string | null; end: string | null };
}

export function MonitoringEvidence({
  uniqueFloats,
  profiles,
  alarmCount,
  dateRange,
}: MonitoringEvidenceProps) {
  if (uniqueFloats.length === 0) {
    return (
      <section className="mb-8 bg-white/[0.03] border border-white/10 rounded-xl p-6 print:bg-gray-50 print:border-gray-200">
        <h2 className="text-[13px] font-semibold text-white/90 mb-3 print:text-gray-900">
          Monitoring Evidence
        </h2>
        <p className="text-[13px] text-white/65 italic print:text-gray-500">
          No Argo float monitoring data available within 200 km.
        </p>
      </section>
    );
  }

  // Aggregate per-float stats
  const floatStats = new Map<
    string,
    { profileCount: number; alarmCount: number; minDistance: number }
  >();

  for (const p of profiles) {
    const existing = floatStats.get(p.platform_id);
    if (existing) {
      existing.profileCount += 1;
      existing.alarmCount += p.alarms.length;
      existing.minDistance = Math.min(existing.minDistance, p.distance_to_claim_km);
    } else {
      floatStats.set(p.platform_id, {
        profileCount: 1,
        alarmCount: p.alarms.length,
        minDistance: p.distance_to_claim_km,
      });
    }
  }

  const dateStr =
    dateRange.start && dateRange.end
      ? `${dateRange.start.slice(0, 10)} \u2013 ${dateRange.end.slice(0, 10)}`
      : "\u2014";

  return (
    <section className="mb-8 bg-white/[0.03] border border-white/10 rounded-xl p-6 print:bg-gray-50 print:border-gray-200">
      <h2 className="text-[13px] font-semibold text-white/90 mb-3 print:text-gray-900">
        Monitoring Evidence
      </h2>

      {/* Summary line */}
      <p className="text-[13px] text-white/70 mb-4 print:text-gray-600">
        {uniqueFloats.length} float{uniqueFloats.length !== 1 ? "s" : ""},{" "}
        {profiles.length} profile{profiles.length !== 1 ? "s" : ""},{" "}
        {alarmCount} alarm{alarmCount !== 1 ? "s" : ""} &middot; {dateStr}
      </p>

      {/* Float table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="text-white/60 border-b border-white/5">
              <th className="py-1 px-2 text-left font-medium">Platform ID</th>
              <th className="py-1 px-2 text-right font-medium">Profiles</th>
              <th className="py-1 px-2 text-right font-medium">Alarms</th>
              <th className="py-1 px-2 text-right font-medium">Min Distance</th>
            </tr>
          </thead>
          <tbody>
            {Array.from(floatStats.entries()).map(([platformId, stats]) => (
              <tr
                key={platformId}
                className="border-b border-white/[0.03] hover:bg-white/[0.02]"
              >
                <td className="py-1 px-2 text-white/80 font-mono">{platformId}</td>
                <td className="py-1 px-2 text-right text-white/70">{stats.profileCount}</td>
                <td className="py-1 px-2 text-right text-white/70">
                  {stats.alarmCount > 0 ? (
                    <span className="text-red-400">{stats.alarmCount}</span>
                  ) : (
                    "0"
                  )}
                </td>
                <td className="py-1 px-2 text-right text-white/60">
                  {stats.minDistance.toFixed(0)} km
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
