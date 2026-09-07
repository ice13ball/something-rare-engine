// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { wodDecadeHex } from "../../../../utils/wodDecades";
import { GEOTRACES_DECADES } from "../../../../utils/geotracesElements";
import { LayerRow, FilterResetLink } from "../../rows";

interface Props {
  expandedFilter: LayerId | null;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function GeotracesRow({ expandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    geotracesElement, setGeotracesElement,
    geotracesDisplayMode, setGeotracesDisplayMode,
    geotracesDecadeFilters, toggleGeotracesDecadeFilter,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  return (
              <LayerRow
                id="geotraces"
                label={t("layers.geotraces.toggle")}
                color="#a78bfa"
                active={activeLayers.has("geotraces")}
                onToggle={() => toggle("geotraces")}
                onLocate={() => flyToLayer?.("geotraces")}
                filterActive={geotracesDecadeFilters.size > 0}
                expanded={expandedFilter === "geotraces"}
                onExpandToggle={() => toggleExpand("geotraces")}
                filterContent={
                  <div className="flex flex-col gap-3">
                    {/* Element selector (display state — not a filter Set) */}
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("layers.geotraces.elementLabel")}</span>
                      <div className="flex gap-1 flex-wrap">
                        {(["mn", "fe", "co", "ni", "cu"] as const).map((el) => (
                          <button
                            key={el}
                            onClick={() => setGeotracesElement(el)}
                            className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors ${
                              geotracesElement === el
                                ? "bg-violet-500 border-violet-500 text-white"
                                : "border-white/20 text-white/65 bg-white/5"
                            }`}
                          >
                            {t(`layers.geotraces.elements.${el}`)}
                          </button>
                        ))}
                      </div>
                    </div>
                    {/* Dots / Hexagons display mode toggle */}
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">View</span>
                      <div className="flex gap-1">
                        {(["dots", "hexes"] as const).map((m) => (
                          <button
                            key={m}
                            onClick={() => setGeotracesDisplayMode(m)}
                            className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors ${
                              geotracesDisplayMode === m
                                ? "bg-violet-500 border-violet-500 text-white"
                                : "border-white/20 text-white/65 bg-white/5"
                            }`}
                          >
                            {m === "dots" ? t("layers.geotraces.dots") : t("layers.geotraces.hexes")}
                          </button>
                        ))}
                      </div>
                    </div>
                    {/* Decade filter — 3 chips covering GEOTRACES IDP2025 range (~2003–2023) */}
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("layers.geotraces.decade")}</span>
                        {geotracesDecadeFilters.size > 0 && (
                          <FilterResetLink
                            show
                            onReset={() => geotracesDecadeFilters.forEach(toggleGeotracesDecadeFilter)}
                          />
                        )}
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {GEOTRACES_DECADES.map((d) => {
                          const decade = String(d);
                          const color = wodDecadeHex(d);
                          const active = geotracesDecadeFilters.size === 0 || geotracesDecadeFilters.has(decade);
                          return (
                            <button
                              key={decade}
                              onClick={() => toggleGeotracesDecadeFilter(decade)}
                              className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors ${
                                active
                                  ? "border-transparent text-white"
                                  : "border-white/20 text-white/65 bg-white/5"
                              }`}
                              style={active ? { backgroundColor: color, borderColor: color } : {}}
                            >
                              {decade}s
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                }
              />
  );
}
