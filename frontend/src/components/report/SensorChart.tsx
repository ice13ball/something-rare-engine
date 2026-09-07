// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import type { SensorPoint } from "../ImpactReport";

interface Props {
  title: string;
  unit: string;
  data: SensorPoint[];
  color: string;
}

export function SensorChart({ title, unit, data, color }: Props) {
  if (data.length === 0) {
    return (
      <div className="bg-white/[0.02] border border-white/5 rounded-lg p-4 text-center text-white/50 text-[13px]">
        No {title} data available
      </div>
    );
  }

  const W = 700;
  const H = 140;
  const PAD = { top: 12, right: 16, bottom: 24, left: 48 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const values = data.map(d => d.value);
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = maxVal - minVal || 1;
  const yMin = minVal - range * 0.05;
  const yMax = maxVal + range * 0.05;
  const yRange = yMax - yMin;

  const x = (i: number) => PAD.left + (i / (data.length - 1 || 1)) * plotW;
  const y = (v: number) => PAD.top + plotH - ((v - yMin) / yRange) * plotH;

  // Build line path
  const linePath = data
    .map((d, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(d.value).toFixed(1)}`)
    .join(" ");

  // Threshold (use the first non-null threshold value)
  const thresholdVal = data.find(d => d.threshold != null)?.threshold ?? null;
  const thresholdY = thresholdVal != null ? y(thresholdVal) : null;

  // Proximity shading: map claim_distance_km to opacity (closer = darker)
  const maxDist = 200; // km — cap for normalization

  const firstDate = data[0].date.slice(0, 10);
  const lastDate = data[data.length - 1].date.slice(0, 10);

  return (
    <div className="bg-white/[0.02] border border-white/5 rounded-lg p-3">
      <p className="text-xs text-white/65 mb-1 font-medium uppercase tracking-wide">
        {title} <span className="text-white/50">({unit})</span>
      </p>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" preserveAspectRatio="xMidYMid meet">
        {/* Proximity shading bands */}
        {data.map((d, i) => {
          if (d.claim_distance_km == null) return null;
          const dist = Math.min(d.claim_distance_km, maxDist);
          const opacity = 0.25 * (1 - dist / maxDist);
          if (opacity < 0.02) return null;
          const barW = plotW / data.length;
          return (
            <rect
              key={i}
              x={x(i) - barW / 2}
              y={PAD.top}
              width={barW}
              height={plotH}
              fill="#7c3aed"
              opacity={opacity}
            />
          );
        })}

        {/* Threshold dashed line */}
        {thresholdY != null && (
          <>
            <line
              x1={PAD.left}
              y1={thresholdY}
              x2={PAD.left + plotW}
              y2={thresholdY}
              stroke="#ef4444"
              strokeWidth={0.8}
              strokeDasharray="6 3"
              opacity={0.5}
            />
            <text
              x={PAD.left + plotW + 2}
              y={thresholdY + 3}
              fill="#ef4444"
              fontSize={8}
              opacity={0.6}
            >
              {thresholdVal!.toFixed(2)}
            </text>
          </>
        )}

        {/* Data line */}
        <path d={linePath} fill="none" stroke={color} strokeWidth={1.5} opacity={0.8} />

        {/* Data dots */}
        {data.map((d, i) => (
          <circle
            key={i}
            cx={x(i)}
            cy={y(d.value)}
            r={d.alarmed ? 4 : 2}
            fill={d.alarmed ? "#ef4444" : color}
            opacity={d.alarmed ? 1 : 0.6}
          />
        ))}

        {/* Y-axis labels */}
        <text x={PAD.left - 4} y={PAD.top + 4} fill="white" fontSize={8} opacity={0.3} textAnchor="end">
          {maxVal.toFixed(1)}
        </text>
        <text x={PAD.left - 4} y={PAD.top + plotH + 1} fill="white" fontSize={8} opacity={0.3} textAnchor="end">
          {minVal.toFixed(1)}
        </text>

        {/* X-axis date labels */}
        <text x={PAD.left} y={H - 4} fill="white" fontSize={8} opacity={0.25} textAnchor="start">
          {firstDate}
        </text>
        <text x={PAD.left + plotW} y={H - 4} fill="white" fontSize={8} opacity={0.25} textAnchor="end">
          {lastDate}
        </text>
      </svg>
    </div>
  );
}
