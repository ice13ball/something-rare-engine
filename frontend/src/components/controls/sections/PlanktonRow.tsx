// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../store/mapStore";
import type { LayerId } from "../../../types/layers";
import {
  PLANKTON_DECADES, PLANKTON_DEPTH_BANDS, PLANKTON_GROUPS, PLANKTON_GROUP_HEX, planktonFilterActive,
} from "../../../utils/plankton";
import { LayerRow, FilterResetLink } from "../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

const CHIP = "px-2 py-0.5 rounded text-[11px] font-mono border transition-colors";
const ON = "border-transparent text-white bg-white/20";
const OFF = "border-white/20 text-white/65 bg-white/5";
const HEADING = "text-[11px] font-mono text-white/70 uppercase tracking-wide";

/** Plankton (OBIS): the four server-side filters. An empty set = every value (all chips lit); the group
 *  chips double as the colour legend. */
export function PlanktonRow({ expandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    planktonGroupFilters, togglePlanktonGroupFilter,
    planktonDecadeFilters, togglePlanktonDecadeFilter,
    planktonDepthFilters, togglePlanktonDepthFilter,
    planktonShowEdna, togglePlanktonShowEdna,
    resetPlanktonFilters,
  } = useMapStore();
  const { t } = useTranslation(["panels", "common"]);
  const narrowed = planktonFilterActive({
    groups: planktonGroupFilters, decades: planktonDecadeFilters, bands: planktonDepthFilters, showEdna: planktonShowEdna,
  });
  const lit = (set: ReadonlySet<string>, v: string) => set.size === 0 || set.has(v);
  const decadeLabel = (d: string) =>
    d === "-1" ? t("filters.plankton.noDate") : d === "1940" ? t("filters.plankton.before1950") : `${d}s`;

  return (
    <LayerRow
      id="plankton-occurrences"
      label={t("layers.planktonOccurrences.toggle")}
      color={PLANKTON_GROUP_HEX.copepoda}
      active={activeLayers.has("plankton-occurrences")}
      onToggle={() => toggle("plankton-occurrences")}
      onLocate={() => flyToLayer?.("plankton-occurrences")}
      filterActive={narrowed}
      expanded={expandedFilter === "plankton-occurrences"}
      onExpandToggle={() => toggleExpand("plankton-occurrences")}
      filterContent={
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-end">
            <FilterResetLink show={narrowed} onReset={resetPlanktonFilters} />
          </div>
          <span className={HEADING}>{t("filters.plankton.groupHeading")}</span>
          <div className="flex flex-wrap gap-1">
            {PLANKTON_GROUPS.map((g) => {
              const on = lit(planktonGroupFilters, g);
              return (
                <button key={g} type="button" aria-pressed={on} onClick={() => togglePlanktonGroupFilter(g)}
                  className={`${CHIP} ${on ? "border-transparent text-white" : OFF}`}
                  style={on ? { backgroundColor: PLANKTON_GROUP_HEX[g], borderColor: PLANKTON_GROUP_HEX[g] } : {}}>
                  {t(`filters.plankton.group.${g}` as any)}
                </button>
              );
            })}
          </div>
          <span className={HEADING}>{t("filters.plankton.decadeHeading")}</span>
          <div className="flex flex-wrap gap-1">
            {PLANKTON_DECADES.map((d) => {
              const on = lit(planktonDecadeFilters, d);
              return (
                <button key={d} type="button" aria-pressed={on} onClick={() => togglePlanktonDecadeFilter(d)}
                  className={`${CHIP} ${on ? ON : OFF}`}>
                  {decadeLabel(d)}
                </button>
              );
            })}
          </div>
          <span className={HEADING}>{t("filters.plankton.depthHeading")}</span>
          <div className="flex flex-wrap gap-1">
            {PLANKTON_DEPTH_BANDS.map((b) => {
              const on = lit(planktonDepthFilters, b);
              return (
                <button key={b} type="button" aria-pressed={on} onClick={() => togglePlanktonDepthFilter(b)}
                  className={`${CHIP} ${on ? ON : OFF}`}>
                  {t(`filters.plankton.depth.${b}` as any)}
                </button>
              );
            })}
          </div>
          <label className="flex items-center gap-2 py-0.5 cursor-pointer text-[11px] text-white/80">
            <input type="checkbox" checked={planktonShowEdna} onChange={() => togglePlanktonShowEdna()} className="w-3 h-3" />
            {t("filters.plankton.showEdna")}
          </label>
          <p className="text-[10px] text-white/60">{t("filters.plankton.ednaNote")}</p>
        </div>
      }
    />
  );
}
