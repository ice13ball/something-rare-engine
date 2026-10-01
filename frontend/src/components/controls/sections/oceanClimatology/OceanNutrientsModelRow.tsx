// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { effectiveBgcMonth, effectiveBgcVariable, type BgcModelMeta, type BgcModelVariable } from "../../../../types/bgcModel";
import { LayerRow } from "../../rows";
import { useFieldLayerToggle } from "./useFieldLayerToggle";

interface Props {
  expandedFilter: LayerId | null;
  setExpandedFilter: (f: LayerId | null) => void;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  nutrientsMeta?: BgcModelMeta | null;
}

/** 0.03, 0.1, 1, 10, 35 — two significant figures, no trailing noise. */
export function formatScaleTick(v: number): string {
  if (v === 0) return "0";
  if (Math.abs(v) >= 100) return v.toFixed(0);
  return String(Number(v.toPrecision(2)));
}

function tickShift(pos: number): string {
  if (pos < 0.06) return "translateX(0)";
  if (pos > 0.94) return "translateX(-100%)";
  return "translateX(-50%)";
}

export function ColourScale({ v }: { v: BgcModelVariable }) {
  const { t } = useTranslation(["panels", "common"]);
  const stops = v.ramp.map((s) => `${s.hex} ${Math.round(s.pos * 100)}%`).join(", ");
  const scaleNote = v.scale === "log" ? t("nutrients.scaleLog")
    : v.scale === "sqrt" ? t("nutrients.scaleSqrt") : null;
  return (
    <div className="flex flex-col gap-1 mt-1">
      <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">
        {t("controls.fieldLayer.scale", { units: v.unit })}
      </span>
      <div className="h-3 w-full rounded-sm border border-white/10" style={{ background: `linear-gradient(to right, ${stops})` }} />
      <div className="relative h-3 text-[10px] font-mono text-white/75">
        {v.ticks.map((tk) => (
          <span key={tk.value} className="absolute whitespace-nowrap" style={{ left: `${tk.pos * 100}%`, transform: tickShift(tk.pos) }}>
            {formatScaleTick(tk.value)}
          </span>
        ))}
      </div>
      {scaleNote && <span className="text-[10px] text-white/55 leading-snug">{scaleNote}</span>}
    </div>
  );
}

export function OceanNutrientsModelRow({ expandedFilter, setExpandedFilter, toggleExpand, toggle, nutrientsMeta }: Props) {
  const {
    activeLayers,
    nutrientsVariable, setNutrientsVariable,
    nutrientsMonth, setNutrientsMonth,
  } = useMapStore();
  const { t } = useTranslation(["panels", "common"]);
  const toggleFieldLayer = useFieldLayerToggle(toggle, expandedFilter, setExpandedFilter);

  const varKey = effectiveBgcVariable(nutrientsMeta ?? null, nutrientsVariable);
  const month = effectiveBgcMonth(nutrientsMeta ?? null, nutrientsMonth);
  const current = nutrientsMeta?.variables.find((v) => v.key === varKey) ?? null;
  const varLabel = (v: BgcModelVariable) => t(`nutrients.variable.${v.key}`, { defaultValue: v.label });

  return (
    <LayerRow
      id="ocean-nutrients-model"
      label={t("layers.oceanNutrientsModel.toggle")}
      color="#3fb98a"
      active={activeLayers.has("ocean-nutrients-model")}
      onToggle={() => toggleFieldLayer("ocean-nutrients-model")}
      expanded={expandedFilter === "ocean-nutrients-model"}
      onExpandToggle={() => toggleExpand("ocean-nutrients-model")}
      filterContent={
        nutrientsMeta && nutrientsMeta.months.length > 0 ? (
          <div className="flex flex-col gap-2">
            <span className="text-[11px] text-orange-300 leading-snug">{t("nutrients.modelWarning")}</span>
            <div className="flex flex-col gap-1">
              <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.variable")}</span>
              <select
                value={varKey ?? ""}
                onChange={(e) => setNutrientsVariable(e.target.value)}
                className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
              >
                {nutrientsMeta.variables.map((v) => (
                  <option key={v.key} value={v.key}>{varLabel(v)} ({v.unit})</option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.month")}</span>
              <select
                value={month ?? ""}
                // The newest month is stored as null ("latest"), so a link keeps following
                // the product instead of freezing on the month that was newest when it was made.
                onChange={(e) => setNutrientsMonth(e.target.value === nutrientsMeta.latest ? null : e.target.value)}
                className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
              >
                {[...nutrientsMeta.months].reverse().map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
            {current && <ColourScale v={current} />}
            {current?.key === "nppv" && (
              <span className="text-[10px] text-white/55 leading-snug">{t("nutrients.nppvHint")}</span>
            )}
            {current?.key === "nstar" && (
              <span className="text-[10px] text-white/55 leading-snug">{t("woaPoint.nstarHint")}</span>
            )}
            <span className="text-[10px] text-white/55 leading-snug">{t("nutrients.clickHint")}</span>
            <span className="text-[10px] text-white/45 leading-snug">{nutrientsMeta.attribution}</span>
          </div>
        ) : null
      }
    />
  );
}
