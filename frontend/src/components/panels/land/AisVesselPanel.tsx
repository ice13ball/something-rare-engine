// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useState, useEffect } from "react";
import { useMapStore } from "../../../store/mapStore";
import { API } from "../shared/tokens";

const SHIP_TYPE_LABELS: Record<number, string> = {
  30: "Fishing", 31: "Towing", 32: "Towing (long)", 33: "Dredging", 34: "Diving ops",
  35: "Military", 36: "Sailing", 37: "Pleasure craft", 50: "Pilot", 51: "SAR",
  52: "Tug", 53: "Port tender", 54: "Anti-pollution", 55: "Law enforcement",
};
function shipTypeLabel(code: number | null | undefined): string {
  if (code == null) return "—";
  const exact = SHIP_TYPE_LABELS[code];
  if (exact) return exact;
  if (code >= 60 && code <= 69) return "Passenger";
  if (code >= 70 && code <= 79) return "Cargo";
  if (code >= 80 && code <= 89) return "Tanker";
  return `Type ${code}`;
}

export function AisVesselPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const mmsi = p.mmsi as number;
  const setVesselFocus = useMapStore(s => s.setVesselFocus);
  const vesselFocus = useMapStore(s => s.vesselFocus);
  const isFocused = vesselFocus?.mmsi === mmsi;
  const name = (p.name as string) || `MMSI ${mmsi}`;
  // If focus was persisted for this mmsi, hydrate showTrack/track from it.
  const [track, setTrack] = useState<GeoJSON.Feature | null>(
    isFocused ? (vesselFocus!.track as unknown as GeoJSON.Feature) : null
  );
  const [showTrack, setShowTrack] = useState(isFocused);

  useEffect(() => {
    if (!showTrack) {
      if (isFocused) setVesselFocus(null);
      return;
    }
    fetch(`${API}/api/v2/vessels/${mmsi}/history?days=30`,
      { headers: { "X-API-Key": import.meta.env.VITE_API_KEY ?? "" } },
    )
      .then(r => r.ok ? r.json() : null)
      .then((fc: GeoJSON.FeatureCollection | null) => {
        setTrack(fc as unknown as GeoJSON.Feature | null);
        if (fc && fc.features?.length) {
          setVesselFocus({ mmsi, name, track: fc });
        }
      })
      .catch(() => {});
  }, [showTrack, mmsi]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Track persists until user clicks "Hide 30-day track" or turns off the
  // Live Vessels layer — NOT when this panel unmounts.

  const sog = p.sog_knots as number | null;
  const ts = p.ts as string | null;
  const fresh = ts ? (Date.now() - new Date(ts).getTime()) / 60000 : null;

  return (
    <div className="space-y-2 text-sm">
      <div>
        <h3 className="text-white/90 font-semibold text-base">{name}</h3>
        <p className="text-xs text-white/50">
          {shipTypeLabel(p.ship_type as number | null)}
          {p.flag ? ` · ${p.flag}` : ""}
        </p>
      </div>

      <div className="rounded border border-cyan-400/30 bg-cyan-400/10 px-2 py-1.5 text-xs text-cyan-200">
        Live AIS · ingested by Abyssal Claims from AISStream.io. No third-party processing.
      </div>

      <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-xs">
        <span className="text-white/40">MMSI</span>          <span className="text-white/80 font-mono">{mmsi}</span>
        {p.imo != null && (<><span className="text-white/40">IMO</span><span className="text-white/80 font-mono">{String(p.imo)}</span></>)}
        {p.callsign != null && (<><span className="text-white/40">Callsign</span><span className="text-white/80 font-mono">{String(p.callsign)}</span></>)}
        {p.length_m != null && (<><span className="text-white/40">Length</span><span className="text-white/80">{String(p.length_m)} m</span></>)}
        {sog != null && (<><span className="text-white/40">Speed</span><span className="text-white/80">{sog.toFixed(1)} kn</span></>)}
        {p.destination != null && String(p.destination).trim() && (
          <><span className="text-white/40">Destination</span><span className="text-white/80 truncate">{String(p.destination)}</span></>
        )}
        {fresh != null && (
          <><span className="text-white/40">Last ping</span>
          <span className={fresh > 30 ? "text-amber-400" : "text-white/80"}>{fresh.toFixed(0)} min ago</span></>
        )}
      </div>

      <button
        onClick={() => setShowTrack(v => !v)}
        className="text-xs text-cyan-300 hover:text-cyan-200 transition"
      >
        {showTrack ? "Hide 30-day track" : "Show 30-day track →"}
      </button>
      {showTrack && track && (track.properties as any)?.count > 0 && (
        <p className="text-xs text-white/50">
          {(track.properties as any).count} of {(track.properties as any).total_points} points
        </p>
      )}
    </div>
  );
}

