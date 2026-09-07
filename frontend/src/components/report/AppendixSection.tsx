// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState } from "react";
import { exportCSV } from "../../utils/reportExport";
import type { ReportData } from "../ImpactReport";

interface Props {
  appendices: ReportData["appendices"];
  platformId: string;
}

export function AppendixSection({ appendices, platformId }: Props) {
  const [expanded, setExpanded] = useState(false);

  const handleSensorCSV = () => {
    const rows = appendices.full_sensor_data.map(p => ({
      profile_id: p.profile_id, date: p.date, lon: p.lon, lat: p.lat,
      depth_m: p.depth_m, surface_temp: p.surface_temp,
      surface_salinity: p.surface_salinity, deep_temp: p.deep_temp,
      deep_salinity: p.deep_salinity, oxygen: p.oxygen, ph: p.ph,
      nearest_claim: p.nearest_claim_name, distance_km: p.distance_to_claim_km,
      alarms: p.alarms.join("; "),
    }));
    exportCSV(rows, `impact-${platformId}-full-sensors.csv`);
  };

  const handleSpeciesCSV = () => {
    const rows = appendices.full_species_list.map(s => ({
      species: s.species, phylum: s.phylum, records: s.records, endangered: s.endangered, iucn_category: s.iucn_category,
    }));
    exportCSV(rows, `impact-${platformId}-species.csv`);
  };

  const handlePlumeCSV = () => {
    const rows = appendices.plume_coordinates.map(p => ({
      profile_id: p.profile_id,
      origin_lon: p.origin[0],
      origin_lat: p.origin[1],
      speed_cms: p.speed_cms,
    }));
    exportCSV(rows, `impact-${platformId}-plumes.csv`);
  };

  const btnCls = "px-2 py-1 text-xs rounded bg-white/5 border border-white/10 text-white/80 hover:bg-white/10 hover:text-white/90 transition-colors print:hidden";

  const cards = [
    {
      title: "Full Sensor Data",
      description: "Complete profile measurements including deep temp/salinity.",
      count: appendices.full_sensor_data.length,
      unit: "profiles",
      onExport: handleSensorCSV,
    },
    {
      title: "Complete Species List",
      description: "All OBIS species observations within 50 km of implicated claims.",
      count: appendices.full_species_list.length,
      unit: "entries",
      onExport: handleSpeciesCSV,
    },
    {
      title: "Plume Path Coordinates",
      description: "RK4-integrated backtrack origin coordinates and current speeds.",
      count: appendices.plume_coordinates.length,
      unit: "paths",
      onExport: handlePlumeCSV,
    },
  ];

  return (
    <section id="appendices" className="mb-8">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 text-xs text-white/55 uppercase tracking-widest mb-3 hover:text-white/65 transition-colors print:text-gray-500"
      >
        7. Appendices
        <span className="text-white/50 print:hidden">{expanded ? "▼" : "▶"}</span>
      </button>

      <div className={`space-y-3 ${expanded ? "" : "hidden print:block"}`}>
        {cards.map(card => (
          <div key={card.title} className="bg-black/30 border border-white/5 rounded-xl p-4 print:bg-gray-50">
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-xs text-white/60 uppercase tracking-wider print:text-gray-500">
                {card.title} ({card.count} {card.unit})
              </h3>
              <button onClick={card.onExport} className={btnCls}>Export CSV</button>
            </div>
            <p className="text-xs text-white/50 print:text-gray-400">{card.description}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
