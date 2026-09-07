// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { memo } from "react";

interface Sample { t: number; v: number }

interface Props {
  samples: Sample[];
  color?: string;
  width?: number;
  height?: number;
  unit?: string;
}

export const Sparkline = memo(function Sparkline({
  samples,
  color = "#5eead4",
  width = 200,
  height = 40,
}: Props) {
  if (samples.length < 2) {
    return <div style={{ width, height }} className="flex items-center justify-center text-white/50 text-[10px]">—</div>;
  }

  const PAD = { l: 2, r: 2, t: 4, b: 4 };
  const pw = width - PAD.l - PAD.r;
  const ph = height - PAD.t - PAD.b;

  const vals = samples.map(s => s.v);
  const minV = Math.min(...vals);
  const maxV = Math.max(...vals);
  const rangeV = maxV - minV || 1;
  const minT = samples[0].t;
  const maxT = samples[samples.length - 1].t;
  const rangeT = maxT - minT || 1;

  const px = (t: number) => PAD.l + ((t - minT) / rangeT) * pw;
  const py = (v: number) => PAD.t + ph - ((v - minV) / rangeV) * ph;

  const path = samples
    .map((s, i) => `${i === 0 ? "M" : "L"}${px(s.t).toFixed(1)},${py(s.v).toFixed(1)}`)
    .join(" ");

  const minIdx = vals.indexOf(minV);
  const maxIdx = vals.indexOf(maxV);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      style={{ display: "block", overflow: "visible" }}
    >
      <path d={path} fill="none" stroke={color} strokeWidth={1.2} opacity={0.8} />
      {/* Min dot */}
      <circle cx={px(samples[minIdx].t)} cy={py(minV)} r={2.5} fill={color} opacity={0.5} />
      {/* Max dot */}
      <circle cx={px(samples[maxIdx].t)} cy={py(maxV)} r={2.5} fill={color} opacity={0.9} />
      {/* Last dot */}
      <circle
        cx={px(samples[samples.length - 1].t)}
        cy={py(vals[vals.length - 1])}
        r={2}
        fill={color}
      />
    </svg>
  );
});
