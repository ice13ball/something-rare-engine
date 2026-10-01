// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { effectiveCoastdomRange } from "../../../../utils/coastdomYearFilter";
import { LayerRow, FilterResetLink } from "../../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

const SELECT_CLS =
  "bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40";

export function CoastdomRow({ expandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const activeLayers = useMapStore((s) => s.activeLayers);
  const range = useMapStore((s) => s.coastdomYearRange);
  const bounds = useMapStore((s) => s.coastdomYearBounds);
  const setRange = useMapStore((s) => s.setCoastdomYearRange);
  const { t } = useTranslation(["panels", "common"]);

  // What is actually filtering (null = full range). The control shows the bounds
  // while nothing is narrowed, so the default reads as "min – max".
  const effective = effectiveCoastdomRange(range, bounds);
  const from = effective?.[0] ?? bounds?.min ?? 0;
  const to = effective?.[1] ?? bounds?.max ?? 0;
  const years = bounds ? Array.from({ length: bounds.max - bounds.min + 1 }, (_, i) => bounds.min + i) : [];

  // Setting both ends back to the bounds stores null, so "full range" is one state.
  const update = (nextFrom: number, nextTo: number) => {
    if (!bounds) return;
    const a = Math.min(nextFrom, nextTo);
    const b = Math.max(nextFrom, nextTo);
    setRange(a <= bounds.min && b >= bounds.max ? null : [a, b]);
  };

  return (
    <LayerRow
      id="coastdom"
      label={t("layers.coastdom.toggle" as any)}
      color="#2dd4bf"
      active={activeLayers.has("coastdom")}
      onToggle={() => toggle("coastdom")}
      onLocate={() => flyToLayer?.("coastdom")}
      filterActive={effective !== null}
      expanded={expandedFilter === "coastdom"}
      onExpandToggle={() => toggleExpand("coastdom")}
      filterContent={
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">
              {t("layers.coastdom.yearFilter.title" as any)}
            </span>
            <FilterResetLink
              show={range !== null}
              onReset={() => setRange(null)}
              label={t("common:reset" as any)}
            />
          </div>
          {bounds ? (
            <>
              <div className="flex items-center gap-2">
                <select
                  aria-label={t("layers.coastdom.yearFilter.from" as any)}
                  value={from}
                  onChange={(e) => update(Number(e.target.value), to)}
                  className={SELECT_CLS}
                >
                  {years.map((y) => <option key={y} value={y}>{y}</option>)}
                </select>
                <span className="text-white/50">–</span>
                <select
                  aria-label={t("layers.coastdom.yearFilter.to" as any)}
                  value={to}
                  onChange={(e) => update(from, Number(e.target.value))}
                  className={SELECT_CLS}
                >
                  {years.map((y) => <option key={y} value={y}>{y}</option>)}
                </select>
              </div>
              <p className="text-[11px] text-white/60 leading-snug">
                {t("layers.coastdom.yearFilter.undatedNote" as any)}
              </p>
            </>
          ) : (
            <p className="text-[11px] text-white/60 leading-snug">
              {t("layers.coastdom.yearFilter.unavailable" as any)}
            </p>
          )}
        </div>
      }
    />
  );
}
