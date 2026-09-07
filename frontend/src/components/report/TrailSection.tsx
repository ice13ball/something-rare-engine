// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useMemo } from "react";
import type { ReportData, SensorPoint, AlarmEntry, PlumeAttribution } from "../ImpactReport";
import { ImpactReportMap } from "../ImpactReportMap";
import { SensorChart } from "./SensorChart";
import { AlarmLog } from "./AlarmLog";

interface Props {
  trail: ReportData["trail"];
  sensorTimelines: Record<string, SensorPoint[]>;
  alarmLog: AlarmEntry[];
  claimPolygons: GeoJSON.FeatureCollection | null;
  plumeAttributions: PlumeAttribution[];
}

export function TrailSection({
  trail,
  sensorTimelines,
  alarmLog,
  claimPolygons,
  plumeAttributions,
}: Props) {
  // Build plume lines by matching profile_id to trail profile coordinates
  const plumeLines = useMemo(() => {
    const profileMap = new Map(
      trail.profiles.map(p => [p.profile_id, [p.lon, p.lat] as [number, number]])
    );
    return plumeAttributions
      .map(pa => {
        const profileCoord = profileMap.get(pa.profile_id);
        if (!profileCoord) return null;
        return { from: pa.backtrack_origin, to: profileCoord };
      })
      .filter((l): l is { from: [number, number]; to: [number, number] } => l != null);
  }, [trail.profiles, plumeAttributions]);

  return (
    <section className="mt-8">
      <h2 className="text-[13px] font-semibold text-white/80 mb-4 uppercase tracking-wide">
        3. Float Trail Analysis
      </h2>

      {/* Trail stats grid */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <div className="bg-white/[0.03] border border-white/5 rounded-lg p-3 text-center">
          <p className="text-[18px] font-semibold text-white/85">{trail.profiles.length}</p>
          <p className="text-xs text-white/55 uppercase tracking-wide mt-0.5">Profiles</p>
        </div>
        <div className="bg-white/[0.03] border border-white/5 rounded-lg p-3 text-center">
          <p className="text-[18px] font-semibold text-white/85">{trail.total_distance_km.toFixed(0)}</p>
          <p className="text-xs text-white/55 uppercase tracking-wide mt-0.5">km Total</p>
        </div>
        <div className="bg-white/[0.03] border border-white/5 rounded-lg p-3 text-center">
          <p className="text-xs font-semibold text-white/85 leading-tight">
            {trail.date_range.start.slice(0, 10)}
          </p>
          <p className="text-xs font-semibold text-white/85 leading-tight">
            {trail.date_range.end.slice(0, 10)}
          </p>
          <p className="text-xs text-white/55 uppercase tracking-wide mt-0.5">Date Range</p>
        </div>
      </div>

      {/* Map */}
      <div className="mb-6 rounded-lg overflow-hidden border border-white/5" style={{ height: 340 }}>
        <ImpactReportMap
          profiles={trail.profiles}
          claimPolygons={claimPolygons}
          plumeLines={plumeLines}
        />
      </div>

      {/* Sensor Timelines */}
      <h3 className="text-[13px] font-medium text-white/65 mb-3 uppercase tracking-wide">
        Sensor Timelines
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-6">
        <SensorChart
          title="Dissolved Oxygen"
          unit="µmol/kg"
          data={sensorTimelines["oxygen"] ?? []}
          color="#f97316"
        />
        <SensorChart
          title="pH"
          unit="pH"
          data={sensorTimelines["ph"] ?? []}
          color="#7c9bb5"
        />
        <SensorChart
          title="Temperature"
          unit="°C"
          data={sensorTimelines["temperature"] ?? []}
          color="#ef4444"
        />
        <SensorChart
          title="Salinity"
          unit="PSU"
          data={sensorTimelines["salinity"] ?? []}
          color="#06b6d4"
        />
      </div>

      {/* Alarm Event Log */}
      <h3 className="text-[13px] font-medium text-white/65 mb-3 uppercase tracking-wide">
        Alarm Event Log
      </h3>
      <AlarmLog alarms={alarmLog} />
    </section>
  );
}
