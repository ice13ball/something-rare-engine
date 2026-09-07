// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

export function VesselTrackPointPanel({ properties: p }: { properties: Record<string, unknown> }) {
  const ts = p.ts as string | undefined;
  const lat = p.lat as number | undefined;
  const lon = p.lon as number | undefined;
  const sog = p.sog_knots as number | null | undefined;
  const cog = p.cog_deg as number | null | undefined;
  const heading = p.heading_deg as number | null | undefined;
  const dest = p.destination as string | null | undefined;
  const name = (p.vessel_name as string) || `MMSI ${p.mmsi}`;
  const when = ts ? new Date(ts) : null;
  return (
    <div className="space-y-2 text-sm">
      <div>
        <h3 className="text-white/90 font-semibold text-base">{name}</h3>
        <p className="text-xs text-white/50">Track point · MMSI {String(p.mmsi)}</p>
      </div>
      <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-xs">
        {when && (<><span className="text-white/40">Time (UTC)</span><span className="text-white/80 font-mono">{when.toISOString().replace("T", " ").slice(0, 16)}</span></>)}
        {lat != null && lon != null && (<>
          <span className="text-white/40">Position</span>
          <span className="text-white/80 font-mono">{lat.toFixed(4)}, {lon.toFixed(4)}</span>
        </>)}
        {sog != null && (<><span className="text-white/40">Speed</span><span className={sog < 1 ? "text-amber-300" : "text-white/80"}>{sog.toFixed(1)} kn {sog < 1 ? "(loitering)" : ""}</span></>)}
        {cog != null && (<><span className="text-white/40">Course</span><span className="text-white/80">{cog.toFixed(0)}°</span></>)}
        {heading != null && (<><span className="text-white/40">Heading</span><span className="text-white/80">{heading.toFixed(0)}°</span></>)}
        {dest != null && String(dest).trim() && (<><span className="text-white/40">Destination</span><span className="text-white/80 truncate">{String(dest)}</span></>)}
      </div>
    </div>
  );
}
