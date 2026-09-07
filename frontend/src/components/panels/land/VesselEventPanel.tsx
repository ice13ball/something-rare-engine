// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

export function VesselEventPanel({ feature }: { feature: any }) {
  const p = feature.properties ?? feature;
  const classification = String(p.classification ?? "ambiguous");
  const gapMin = p.ais_gap_seconds != null ? Math.round((p.ais_gap_seconds as number) / 60) : null;

  return (
    <div className="space-y-3 text-sm">
      <div>
        <p className="font-semibold text-white/90">
          {classification === "dark" ? "Dark vessel (SAR, no AIS)"
           : classification === "ambiguous" ? "Unconfirmed vessel (SAR, no AIS nearby)"
           : p.vessel_name ?? (p.matched_mmsi ? `MMSI ${p.matched_mmsi}` : "Vessel event")}
        </p>
        {p.ts && (
          <p className="text-xs text-white/50 mt-0.5">
            {new Date(p.ts as string).toUTCString().slice(0, 22)}
          </p>
        )}
      </div>

      <div className="flex flex-wrap gap-1">
        <span className={
          "px-2 py-0.5 rounded-full text-xs " +
          (classification === "matched" ? "bg-emerald-500/20 text-emerald-300"
           : classification === "dark"  ? "bg-red-500/20 text-red-300"
                                        : "bg-amber-500/20 text-amber-300")
        }>
          {classification}
        </span>
        {p.contractor_name && (
          <span
            className="px-2 py-0.5 rounded-full text-xs bg-cyan-500/20 text-cyan-300"
            title={p.contractor_role ? `Role: ${p.contractor_role}` : undefined}
          >
            {p.contractor_short ?? p.contractor_name}
          </span>
        )}
        {p.inside_polygon_type && (
          <span
            className="px-2 py-0.5 rounded-full text-xs bg-violet-500/20 text-violet-300"
            title={
              p.inside_polygon_type === "isa_concession"
                ? `ISA concession ${p.inside_polygon_id ?? ""}`
                : p.inside_polygon_type === "contractor_watchbox"
                  ? "10 km watchbox around a known contractor vessel"
                  : String(p.inside_polygon_type)
            }
          >
            Inside {p.inside_polygon_name
              ? String(p.inside_polygon_name)
              : String(p.inside_polygon_type).replace("_", " ")}
          </span>
        )}
      </div>

      <div className="space-y-1">
        {p.matched_mmsi != null && (
          <div className="flex justify-between">
            <span className="text-white/50">Matched MMSI</span>
            <span className="text-white/80">{String(p.matched_mmsi)}</span>
          </div>
        )}
        {gapMin != null && (
          <div className="flex justify-between">
            <span className="text-white/50">AIS gap</span>
            <span className="text-white/80">{gapMin} min</span>
          </div>
        )}
        {classification !== "matched" && p.coverage_neighbors != null && (
          <div className="flex justify-between">
            <span className="text-white/50">AIS coverage</span>
            <span className="text-white/80">
              {(p.coverage_neighbors as number) > 0
                ? `${p.coverage_neighbors} other vessel(s) heard within 50 km / ±1 h`
                : "no AIS received nearby — unconfirmed"}
            </span>
          </div>
        )}
        {p.sar_detection_id && (
          <div className="flex justify-between">
            <span className="text-white/50">SAR detection</span>
            <span className="text-white/80 font-mono text-xs">{p.sar_detection_id}</span>
          </div>
        )}
        {p.inside_polygon_type === "isa_concession" && p.inside_polygon_id && (
          <div className="flex justify-between">
            <span className="text-white/50">ISA contract</span>
            <span className="text-white/80 font-mono text-xs">{String(p.inside_polygon_id)}</span>
          </div>
        )}
        <div className="flex justify-between">
          <span className="text-white/50">Location</span>
          <span className="text-white/80">
            {typeof p.lat === "number" ? `${(p.lat as number).toFixed(3)}°, ${(p.lon as number).toFixed(3)}°` : "—"}
          </span>
        </div>
      </div>

      {p.s2_thumbnail_url && (
        <div>
          <p className="text-xs text-white/40 uppercase tracking-wide mb-1">Sentinel-2 confirmation</p>
          <img src={p.s2_thumbnail_url as string} alt="S2 optical thumbnail" className="rounded border border-white/10" />
        </div>
      )}

      {classification !== "matched" && (
        <div className="pt-2 border-t border-white/10 text-xs text-white/40">
          {classification === "dark"
            ? "‘Dark’: no AIS match though other vessels’ AIS was received here at this time — a credible AIS-off signal, not proof of wrongdoing."
            : "‘Ambiguous’: no AIS reception nearby, so a dark vessel cannot be distinguished from an AIS-coverage gap."}
        </div>
      )}

      <div className="pt-2 border-t border-white/10 text-xs text-white/40">
        Sources: Sentinel-1 SAR (CDSE, Copernicus) × raw AIS (AISStream.io). Correlation by Abyssal Claims.
      </div>
    </div>
  );
}
