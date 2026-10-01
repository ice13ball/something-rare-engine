// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import {
  effectiveOceanColourMonth, effectiveOceanColourVariable,
  type OceanColourMeta, type OceanColourVariable,
} from "../../../../types/oceanColour";
import { LayerRow } from "../../rows";
import { useFieldLayerToggle } from "./useFieldLayerToggle";
import { ColourScale } from "./OceanNutrientsModelRow";

interface Props {
  expandedFilter: LayerId | null;
  setExpandedFilter: (f: LayerId | null) => void;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  oceanColourMeta?: OceanColourMeta | null;
}

export function OceanColourRow({ expandedFilter, setExpandedFilter, toggleExpand, toggle, oceanColourMeta }: Props) {
  const {
    activeLayers,
    oceanColourVariable, setOceanColourVariable,
    oceanColourMonth, setOceanColourMonth,
  } = useMapStore();
  const { t } = useTranslation(["panels", "common"]);
  const toggleFieldLayer = useFieldLayerToggle(toggle, expandedFilter, setExpandedFilter);

  const meta = oceanColourMeta ?? null;
  const varKey = effectiveOceanColourVariable(meta, oceanColourVariable);
  const month = effectiveOceanColourMonth(meta, oceanColourMonth);
  const current = meta?.variables.find((v) => v.key === varKey) ?? null;
  const varLabel = (v: OceanColourVariable) => t(`oceanColour.variable.${v.key}`, { defaultValue: v.label });
  const monthLabel = (m: string) => {
    const p = meta?.month_products[m];
    return p ? `${m} · ${t(`oceanColour.product.${p}`)}` : m;
  };

  return (
    <LayerRow
      id="ocean-colour-satellite"
      label={t("layers.oceanColourSatellite.toggle")}
      color="#2fa5b8"
      active={activeLayers.has("ocean-colour-satellite")}
      onToggle={() => toggleFieldLayer("ocean-colour-satellite")}
      expanded={expandedFilter === "ocean-colour-satellite"}
      onExpandToggle={() => toggleExpand("ocean-colour-satellite")}
      filterContent={
        meta && meta.months.length > 0 ? (
          <div className="flex flex-col gap-2">
            <span className="text-[11px] text-sky-300 leading-snug">{t("oceanColour.satelliteNote")}</span>
            <div className="flex flex-col gap-1">
              <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.variable")}</span>
              <select
                value={varKey ?? ""}
                onChange={(e) => setOceanColourVariable(e.target.value)}
                className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
              >
                {meta.variables.map((v) => (
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
                onChange={(e) => setOceanColourMonth(e.target.value === meta.latest ? null : e.target.value)}
                className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
              >
                {[...meta.months].reverse().map((m) => (
                  <option key={m} value={m}>{monthLabel(m)}</option>
                ))}
              </select>
            </div>
            {current && <ColourScale v={current} />}
            {current?.key === "pp" && (
              <span className="text-[10px] text-white/55 leading-snug">{t("oceanColour.ppHint")}</span>
            )}
            <span className="text-[10px] text-white/55 leading-snug">{t("oceanColour.gapHint")}</span>
            <span className="text-[10px] text-white/55 leading-snug">{t("oceanColour.clickHint")}</span>
            <span className="text-[10px] text-white/45 leading-snug">{meta.attribution}</span>
          </div>
        ) : null
      }
    />
  );
}
