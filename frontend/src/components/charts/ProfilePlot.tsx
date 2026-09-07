// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { memo } from "react";

export interface ProfileVariable {
  key: string;
  label: string;
  unit: string;
  color: string;
  values: number[];
}

interface Props {
  depths: number[];
  variables: ProfileVariable[];
  castTime?: string;
  width?: number;
  height?: number;
}

export const ProfilePlot = memo(function ProfilePlot({
  depths,
  variables,
  castTime,
  width = 280,
  height = 180,
}: Props) {
  if (!depths.length || !variables.length) return null;

  const PAD = { top: 8, right: 16, bottom: 20, left: 40 };
  const pw = width - PAD.left - PAD.right;
  const ph = height - PAD.top - PAD.bottom;

  // Y axis: depth (inverted — 0 at top = surface)
  const maxDepth = Math.max(...depths);
  const minDepth = Math.min(...depths);
  const yRange = maxDepth - minDepth || 1;
  const py = (d: number) => PAD.top + ((d - minDepth) / yRange) * ph;

  // Each variable has its own X axis range
  const lines = variables.map(v => {
    const minVal = Math.min(...v.values);
    const maxVal = Math.max(...v.values);
    const range  = maxVal - minVal || 1;
    const px = (val: number) => PAD.left + ((val - minVal) / range) * pw;
    const path = depths
      .map((d, i) => `${i === 0 ? "M" : "L"}${px(v.values[i]).toFixed(1)},${py(d).toFixed(1)}`)
      .join(" ");
    return { ...v, minVal, maxVal, path };
  });

  return (
    <div>
      {castTime && (
        <p className="text-[10px] text-white/60 mb-1">
          Cast: {castTime.slice(0, 16).replace("T", " ")} UTC
        </p>
      )}
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" style={{ display: "block" }}>
        {/* Depth axis */}
        <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={PAD.top + ph}
          stroke="rgba(255,255,255,0.1)" strokeWidth={0.5} />
        <text x={PAD.left - 4} y={PAD.top + 4} fill="rgba(255,255,255,0.25)" fontSize={7}
          textAnchor="end">{Math.round(minDepth)}m</text>
        <text x={PAD.left - 4} y={PAD.top + ph} fill="rgba(255,255,255,0.25)" fontSize={7}
          textAnchor="end">{Math.round(maxDepth)}m</text>

        {/* Data lines */}
        {lines.map(v => (
          <g key={v.key}>
            <path d={v.path} fill="none" stroke={v.color} strokeWidth={1.5} opacity={0.8} />
          </g>
        ))}
      </svg>

      {/* Legend */}
      <div className="flex flex-wrap gap-2 mt-1">
        {lines.map(v => (
          <span key={v.key} className="text-[11px] flex items-center gap-1">
            <span className="inline-block w-3 border-t-2" style={{ borderColor: v.color }} />
            <span style={{ color: v.color }}>{v.label}</span>
            <span className="text-white/60">({v.unit})</span>
          </span>
        ))}
      </div>
    </div>
  );
});
