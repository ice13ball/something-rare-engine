// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { memo } from "react";

interface Props {
  // strip[timeIdx][binIdx] = mean backscatter in dB, or null where ONC reported no
  // sample. Null cells are left unpainted rather than drawn as zero — 0 dB is a real
  // backscatter value and would read as a measurement.
  strip: (number | null)[][];
  // Bin depths in metres, ascending (shallow → deep), aligned with binIdx.
  depths?: number[];
  units?: string;
  windowStart: string;
  windowEnd: string;
  width?: number;
  height?: number;
}

// Viridis-approximation: 5 control points mapped to [0, 1]
const VIRIDIS = [
  [68, 1, 84],
  [59, 82, 139],
  [33, 145, 140],
  [94, 201, 98],
  [253, 231, 37],
] as const;

function viridisColor(t: number): string {
  const clamped = Math.max(0, Math.min(1, t));
  const seg = clamped * (VIRIDIS.length - 1);
  const lo = Math.floor(seg);
  const hi = Math.min(lo + 1, VIRIDIS.length - 1);
  const f = seg - lo;
  const r = Math.round(VIRIDIS[lo][0] + f * (VIRIDIS[hi][0] - VIRIDIS[lo][0]));
  const g = Math.round(VIRIDIS[lo][1] + f * (VIRIDIS[hi][1] - VIRIDIS[lo][1]));
  const b = Math.round(VIRIDIS[lo][2] + f * (VIRIDIS[hi][2] - VIRIDIS[lo][2]));
  return `rgb(${r},${g},${b})`;
}

export const AdcpHeatmap = memo(function AdcpHeatmap({
  strip,
  depths,
  units = "dB",
  windowStart,
  windowEnd,
  width = 320,
  height = 100,
}: Props) {
  if (!strip || strip.length === 0) return null;

  const nTime = strip.length;
  const nBins = strip[0]?.length ?? 0;
  if (nBins === 0) return null;

  // Find global min/max for normalization, ignoring gaps. A null must not
  // participate: `null < Infinity` coerces to 0 and would pin minVal at zero.
  let minVal = Infinity;
  let maxVal = -Infinity;
  for (const row of strip) {
    for (const v of row) {
      if (v === null || !Number.isFinite(v)) continue;
      if (v < minVal) minVal = v;
      if (v > maxVal) maxVal = v;
    }
  }
  if (maxVal === -Infinity) return null;  // every cell is a gap
  const range = maxVal - minVal || 1;

  const cellW = width / nTime;
  const cellH = height / nBins;

  const startLabel = windowStart.slice(11, 16);
  const endLabel   = windowEnd.slice(11, 16);

  // Fall back to the old qualitative labels only when the row predates the
  // RADCPTS migration and carries no depth axis.
  const hasDepths = Array.isArray(depths) && depths.length === nBins;
  const fmt = (m: number) => `${Math.round(m).toLocaleString()} m`;
  const shallowLabel = hasDepths ? fmt(depths![0]) : "surface";
  const deepLabel    = hasDepths ? fmt(depths![nBins - 1]) : "deep";

  return (
    <div>
      <svg
        viewBox={`0 0 ${width} ${height + 12}`}
        width="100%"
        style={{ display: "block" }}
      >
        {strip.map((row, ti) =>
          row.map((val, bi) => {
            if (val === null || !Number.isFinite(val)) return null;
            const t = (val - minVal) / range;
            return (
              <rect
                key={`${ti}-${bi}`}
                x={ti * cellW}
                y={bi * cellH}
                width={Math.ceil(cellW)}
                height={Math.ceil(cellH)}
                fill={viridisColor(t)}
                opacity={0.9}
              />
            );
          })
        )}
        {/* X-axis labels */}
        <text x={0} y={height + 10} fill="rgba(255,255,255,0.25)" fontSize={7}>
          {startLabel}
        </text>
        <text x={width} y={height + 10} textAnchor="end" fill="rgba(255,255,255,0.25)" fontSize={7}>
          {endLabel}
        </text>
        {/* Y-axis: real bin depths when we have them. Bin 0 is the shallowest —
            the parser sorts ascending, because ONC ships depth descending. */}
        <text x={2} y={8} fill="rgba(255,255,255,0.25)" fontSize={7}>
          {shallowLabel}
        </text>
        <text x={2} y={height - 2} fill="rgba(255,255,255,0.25)" fontSize={7}>
          {deepLabel}
        </text>
      </svg>
      {/* Colorbar legend */}
      <div className="flex justify-between text-[9px] text-white/55 mt-0.5">
        <span>{`${minVal.toFixed(1)} ${units}`}</span>
        <span>{`${maxVal.toFixed(1)} ${units}`}</span>
      </div>
    </div>
  );
});
