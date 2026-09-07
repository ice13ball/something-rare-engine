// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

// Shared within the arctic domain only: MiniLineChart (ArcticRiverPanel) and
// MiniBar (ArcticCatchmentPanel's SocDepthChart) are each single-panel helpers
// that happen to share this file because two panels in the SAME domain use them.

/** Tiny inline SVG sparkline for a monthly time-series [[YYYY-MM, val], ...]. */
export function MiniLineChart({
  data,
  label,
  unit = "",
  color = "rgb(34 211 238)",
}: {
  data: [string, number][];
  label: string;
  unit?: string;
  color?: string;
}) {
  if (data.length < 2) return null;
  const vals = data.map(([, v]) => v);
  const min  = Math.min(...vals);
  const max  = Math.max(...vals);
  const range = max - min || 1;
  const W = 180;
  const H = 40;
  const px = (i: number) => (i / (data.length - 1)) * W;
  const py = (v: number) => H - ((v - min) / range) * H;
  const points = data.map(([, v], i) => `${px(i).toFixed(1)},${py(v).toFixed(1)}`).join(" ");
  return (
    <div className="mt-1 mb-2">
      <p className="text-[11px] text-white/65 mb-0.5">{label}</p>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} className="block overflow-visible">
        <polyline points={points} fill="none" stroke={color} strokeOpacity={0.85} strokeWidth={1.5} strokeLinejoin="round" />
        {data.map(([, v], i) => (
          <circle key={i} cx={px(i)} cy={py(v)} r={1.8} fill={color} />
        ))}
      </svg>
      <div className="flex justify-between text-[10px] text-white/60 font-mono mt-0.5">
        <span>{data[0][0].slice(0, 7)}</span>
        <span>{max.toLocaleString(undefined, { maximumFractionDigits: 1 })} {unit}</span>
        <span>{data[data.length - 1][0].slice(0, 7)}</span>
      </div>
    </div>
  );
}

/** Horizontal mini bar: pct 0–1 in a given colour. */
export function MiniBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="h-2 rounded-sm overflow-hidden bg-white/10 w-full">
      <div className="h-full rounded-sm" style={{ width: `${Math.min(pct * 100, 100)}%`, backgroundColor: color }} />
    </div>
  );
}
