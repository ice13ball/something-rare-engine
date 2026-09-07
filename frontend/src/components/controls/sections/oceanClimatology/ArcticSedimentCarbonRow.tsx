// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { useTranslation } from "react-i18next";
import { useMapStore, type CascadeVariable } from "../../../../store/mapStore";
import type { LayerId } from "../../../../types/layers";
import { CASCADE_DECADES } from "../../filterDefs";
import { LayerRow, FilterResetLink } from "../../rows";
import { useFieldLayerToggle } from "./useFieldLayerToggle";

interface Props {
  expandedFilter: LayerId | null;
  setExpandedFilter: (f: LayerId | null) => void;
  toggleExpand: (id: LayerId) => void;
  toggle: (id: LayerId) => void;
  flyToLayer: ((id: LayerId) => void) | null;
}

export function ArcticSedimentCarbonRow({ expandedFilter, setExpandedFilter, toggleExpand, toggle, flyToLayer }: Props) {
  const {
    activeLayers,
    cascadeVariable, setCascadeVariable,
    cascadeDisplayMode, setCascadeDisplayMode,
    cascadeDecadeFilters, toggleCascadeDecadeFilter,
  } = useMapStore();

  const { t } = useTranslation(["panels", "common"]);

  const toggleFieldLayer = useFieldLayerToggle(toggle, expandedFilter, setExpandedFilter);

  return (
              <LayerRow
                id="arctic-sediment-carbon"
                label={t("layers.arcticSedimentCarbon.toggle")}
                color="#d4a373"
                active={activeLayers.has("arctic-sediment-carbon")}
                onToggle={() => toggleFieldLayer("arctic-sediment-carbon")}
                onLocate={() => flyToLayer?.("arctic-sediment-carbon")}
                filterActive={cascadeDecadeFilters.size > 0}
                expanded={expandedFilter === "arctic-sediment-carbon"}
                onExpandToggle={() => toggleExpand("arctic-sediment-carbon")}
                filterContent={
                  <div className="flex flex-col gap-3">
                    {/* Field / Stations display mode toggle */}
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] uppercase tracking-wide text-white/50">
                        {t("controls.fieldLayer.display")}
                      </span>
                      <div className="flex gap-1">
                        {(["field", "stations"] as const).map((m) => (
                          <button key={m} onClick={() => setCascadeDisplayMode(m)}
                            className={`px-2 py-1 rounded text-xs border ${cascadeDisplayMode === m
                              ? "bg-cyan-400/20 border-cyan-400/50 text-cyan-300"
                              : "bg-white/5 border-white/10 text-white/60"}`}>
                            {m === "field" ? t("controls.fieldLayer.field") : t("layers.arcticSedimentCarbon.stations")}
                          </button>
                        ))}
                      </div>
                    </div>
                    {/* Variable selector */}
                    <div className="flex flex-col gap-1">
                      <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("controls.fieldLayer.variable")}</span>
                      <select
                        value={cascadeVariable}
                        onChange={(e) => setCascadeVariable(e.target.value as CascadeVariable)}
                        className="w-full bg-white/5 text-white/90 text-[12px] font-mono rounded px-2 py-1 border border-white/10 focus:outline-none focus:border-cyan-400/40"
                      >
                        <option value="oc">{t("layers.arcticSedimentCarbon.var.oc")}</option>
                        <option value="tn">{t("layers.arcticSedimentCarbon.var.tn")}</option>
                        <option value="d13c">{t("layers.arcticSedimentCarbon.var.d13c")}</option>
                        <option value="d14c">{t("layers.arcticSedimentCarbon.var.d14c")}</option>
                      </select>
                    </div>
                    {/* Decade filter — only meaningful in Stations mode; the field is a
                        ready-made CASCADE raster with no time axis to filter on. */}
                    {cascadeDisplayMode === "stations" ? (
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center justify-between">
                          <span className="text-[11px] font-mono text-white/70 uppercase tracking-wide">{t("layers.arcticSedimentCarbon.decade")}</span>
                          <FilterResetLink
                            show={cascadeDecadeFilters.size > 0}
                            onReset={() => cascadeDecadeFilters.forEach(toggleCascadeDecadeFilter)}
                          />
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {CASCADE_DECADES.map((decade) => {
                            const active = cascadeDecadeFilters.size === 0 || cascadeDecadeFilters.has(decade);
                            const label = decade === "undated"
                              ? t("sampleDate.undatedSuffix", { ns: "legend" })
                              : `${decade}s`;
                            return (
                              <button
                                key={decade}
                                onClick={() => toggleCascadeDecadeFilter(decade)}
                                className={`px-2 py-0.5 rounded text-[11px] font-mono border transition-colors ${
                                  active
                                    ? "bg-cyan-400/20 border-cyan-400/50 text-cyan-300"
                                    : "border-white/20 text-white/65 bg-white/5"
                                }`}
                              >
                                {label}
                              </button>
                            );
                          })}
                        </div>
                      </div>
                    ) : (
                      <p className="text-[11px] text-white/60 leading-snug">
                        {t("layers.arcticSedimentCarbon.fieldHasNoDecadeFilter", { ns: "legend" })}
                      </p>
                    )}
                  </div>
                }
              />
  );
}
